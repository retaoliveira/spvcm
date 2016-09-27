import warnings
from datetime import datetime as dt
import numpy as np
import pysal as ps
import copy
import multiprocessing as mp
import sqlite3 as sql
from .sqlite import head_to_sql, start_sql
from .plotting.traces import plot_trace
import pandas as pd
import os

######################
# SAMPLER MECHANISMS #
######################

class Sampler_Mixin(object):
    def __init__(self):
        pass

    def sample(self, n_samples, n_jobs=1):
        """
        Sample from the joint posterior distribution defined by all of the
        parameters in the gibbs sampler.

        Parameters
        ----------
        n_samples      :   int
                        number of samples from the joint posterior density to
                        take

        Returns
        -------
        updates all values in place, may return trace of sampling run if pop is
        True
        """
        if n_jobs > 1:
           self._parallel_sample(n_samples, n_jobs)
           return
        elif isinstance(self.state, list):
            self._parallel_sample(n_samples, n_jobs=len(self.state))
            return
        _start = dt.now()
        try:
            while n_samples > 0:
                if (self._verbose > 1) and (n_samples % 100 == 0):
                    print('{} Draws to go'.format(n_samples))
                self.draw()
                n_samples -= 1
        except KeyboardInterrupt:
            warnings.warn('Sampling interrupted, drew {} samples'.format(self.cycles))
        finally:
            _stop = dt.now()
            if not hasattr(self, 'total_sample_time'):
                self.total_sample_time = _stop - _start
            else:
                self.total_sample_time += _stop - _start

    def draw(self):
        """
        Take exactly one sample from the joint posterior distribution
        """
        if self.cycles == 0:
            self._finalize_invariants()
        self._iteration()
        self.cycles += 1
        for param in self.traced_params:
            self.trace.chains[0][param].append(self.state[param])
        if self.database is not None:
            head_to_sql(self, self._cur, self._cxn)
            for param in self.traced_params:
                self.trace[param] = [getattr(self.trace, param)[-1]]
    
    def _parallel_sample(self, n_samples, n_jobs):
        models = [copy.deepcopy(self) for _ in range(n_jobs)]
        for i, model in enumerate(models):
            if isinstance(model.state, list):
                models[i].state = copy.deepcopy(self.state[i])
            if self.database is not None:
                models[i].database = self.database + str(i)
            models[i].trace = Trace(**{k:[] for k in model.trace.varnames})
            if self.cycles == 0:
                self._fuzz_starting_values(self)
        n_samples = [n_samples] * n_jobs
        seed = np.random.randint(0,10000, size=n_jobs).tolist()
        P = mp.Pool(n_jobs)
        results = P.map(_reflexive_sample, zip(models, n_samples, seed))
        P.close()
        if self.cycles > 0:
            new_traces = []
            for i, model in enumerate(results):
                new_traces.append(Hashmap(**{k:param + model.trace.chains[0][k]
                                             for k, param in self.trace.chains[i].items()}))
            new_trace = Trace(*new_traces)
        else:
            new_trace = Trace(*[model.trace.chains[0] for model in results])
        self.trace = new_trace
        self.state = [model.state for model in results]
        self.cycles += n_samples[0]
    
    def _fuzz_starting_values(self, state):
        pass

    @property
    def database(self):
        return getattr(self, '_db', None)
        
    @database.setter
    def database(self, filename):
        self._cxn, self._cur = start_sql(self, tracename=filename)
        self._db = filename

def _reflexive_sample(tup):
    """
    a helper function sample a bunch of models in parallel.
    
    Tuple must be:
    
    model : model object
    n_samples : int number of samples
    seed : seed to use for the sampler
    """
    model, n_samples, seed = tup
    np.random.seed(seed)
    model.sample(n_samples=n_samples)
    return model

def _noop(*args, **kwargs):
    pass

#######################
# MAPS AND CONTAINERS #
#######################

class Hashmap(dict):
    """
    A dictionary with dot access on attributes
    """
    def __init__(self, **kw):
        super(Hashmap, self).__init__(**kw)
        if kw != dict():
            for k in kw:
                self[k] = kw[k]

    def __getattr__(self, attr):
        try:
            r = self[attr]
        except KeyError:
            try:
                r = getattr(super(Hashmap, self), attr)
            except AttributeError:
                raise AttributeError("'{}' object has no attribute '{}'"
                                     .format(self.__class__, attr))
        return r

    def __setattr__(self, key, value):
        self.__setitem__(key, value)

    def __setitem__(self, key, value):
        super(Hashmap, self).__setitem__(key,value)
        self.__dict__.update({key:value})

    def __delattr__(self, item):
        self.__delitem__(item)

    def __delitem__(self, key):
        super(Hashmap, self).__delitem__(key)
        del self.__dict__[key]
        
class Trace(object):
    def __init__(self, *chains, **kwargs):
        if chains is () and kwargs != dict():
            self.chains = _maybe_hashmap(kwargs)
        if chains is not ():
            self.chains = _maybe_hashmap(*chains)
            if kwargs != dict():
                self.chains.extend(_maybe_hashmap(kwargs))
        self._validate_schema()
    
    @property
    def varnames(self, chain=None):
        try:
            return self._varnames
        except AttributeError:
            try:
                self._validate_schema()
            except KeyError:
                if chain is None:
                    raise Exception('Variable names are heterogeneous in chains and no default index provided.')
                else:
                    warn('Variable names are heterogenous in chains!', stacklevel=2)
                    return list(self.chains[chain].keys())
            self._varnames = list(self.chains[0].keys())
            return self._varnames
    
    def drop(self, *varnames, inplace=True):
        if not inplace:
            new = copy.deepcopy(self)
            new.drop(*varnames, inplace=True)
            new._varnames = list(new.chains[0].keys())
            return new
        for i, chain in enumerate(self.chains):
            for varname in varnames:
                del self.chains[i][varname]
        self._varnames = list(self.chains[0].keys())
            

    def _validate_schema(self):
        tracked_in_each = [set(chain.keys()) for chain in self.chains]
        same_schema = [names == tracked_in_each[0] for names in tracked_in_each]
        try:
            assert all(same_schema)
        except AssertionError:
            bad_chains = [i for i in range(self.n_chains) if same_schema[i]]
            KeyError('The parameters tracked in each chain are not the same!'
                     '\nChains {} do not have the same parameters as chain 1!'.format(bad_chains))

    @property
    def n_chains(self):
        return len(self.chains)

    def __getitem__(self, key):
        """
        Getting an item from a trace can be done using at most three indices, where:

        1 index
        --------
            str/list of str: names of variates in all chains to grab. Returns list of Hashmaps
            slice/int: iterations to grab from all chains. Returns list of Hashmaps, sliced to the specification

        2 index
        -------
            (str/list of str, slice/int): first term is name(s) of variates in all chains to grab,
                                          second term specifies the slice each chain.
                                          returns: list of hashmaps with keys of first term and entries sliced by the second term.
            (slice/int, str/list of str): first term specifies which chains to retrieve,
                                          second term is name(s) of variates in those chains
                                          returns: list of hashmaps containing all iterations
            (slice/int, slice/int): first term specifies which chains to retrieve,
                                    second term specifies the slice of each chain.
                                    returns: list of hashmaps with entries sliced by the second term
        3 index
        --------
            (slice/int, str/list of str, slice/int) : first term specifies which chains to retrieve,
                                                      second term is the name(s) of variates in those chains,
                                                      third term is the iteration slicing.
                                                      returns: list of hashmaps keyed on second term, with entries sliced by the third term
        """
        if isinstance(key, str): #user wants only one name from the trace
            if self.n_chains  > 1:
                result = ([chain[key] for chain in self.chains])
            else:
                result = (self.chains[0][key])
        elif isinstance(key, (slice, int)): #user wants all draws past a certain index
            if self.n_chains > 1:
                return [Hashmap(**{k:v[key] for k,v in chain.items()}) for chain in self.chains]
            else:
                return Hashmap(**{k:v[key] for k,v in self.chains[0].items()})
        elif isinstance(key, list) and all([isinstance(val, str) for val in key]): #list of atts over all iters and all chains
                if self.n_chains > 1:
                    return [Hashmap(**{k:chain[k] for k in key}) for chain in self.chains]
                else:
                    return Hashmap(**{k:self.chains[0][k] for k in key})
        elif isinstance(key, tuple): #complex slicing
            if len(key) == 1:
                return self[key[0]] #ignore empty blocks
            if len(key) == 2:
                head, tail = key
                if isinstance(head, str): #all chains, one var, some iters
                    if self.n_chains > 1:
                        result = ([_ifilter(tail, chain[head]) for chain in self.chains])
                    else:
                        result = (_ifilter(tail, self.chains[0][head]))
                elif isinstance(head, list) and all([isinstance(v, str) for v in head]): #all chains, some vars, some iters
                    if self.n_chains > 1:
                        return [Hashmap(**{name:_ifilter(tail, chain[name]) for name in head})
                                   for chain in self.chains]
                    else:
                        chain = self.chains[0]
                        return Hashmap(**{name:_ifilter(tail, chain[name]) for name in head})
                elif isinstance(tail, str):
                    target_chains = _ifilter(head, self.chains)
                    if isinstance(target_chains, Hashmap):
                        target_chains = [target_chains]
                    if len(target_chains) > 1:
                        result = ([chain[tail] for chain in target_chains])
                    elif len(target_chains) == 1:
                        result = (target_chains[0][tail])
                    else:
                        raise IndexError('The supplied chain index {} does not'
                                        ' match any chains in trace.chains'.format(head))
                elif isinstance(tail, list) and all([isinstance(v, str) for v in tail]):
                    target_chains = _ifilter(head, self.chains)
                    if isinstance(target_chains, Hashmap):
                        target_chains = [target_chains]
                    if len(target_chains) > 1:
                        return [Hashmap(**{k:chain[k] for k in tail}) for chain in target_chains]
                    elif len(target_chains) == 1:
                        return Hashmap(**{k:target_chains[0][k] for k in tail})
                    else:
                        raise IndexError('The supplied chain index {} does not'
                                         ' match any chains in trace.chains'.format(head))
                else:
                    target_chains = _ifilter(head, self.chains)
                    if isinstance(target_chains, Hashmap):
                        target_chains = [target_chains]
                    out = [Hashmap(**{k:_ifilter(tail, val) for k,val in chain.items()})
                            for chain in target_chains]
                    if len(out) == 1:
                        return out[0]
                    else:
                        return out
            elif len(key) == 3:
                chidx, varnames, iters = key
                if isinstance(chidx, int):
                    if np.abs(chidx) > self.n_chains:
                        raise IndexError('The supplied chain index {} does not'
                                         ' match any chains in trace.chains'.format(chidx))
                if varnames == slice(None, None, None):
                    varnames = self.varnames
                chains = _ifilter(chidx, self.chains)
                if isinstance(chains, Hashmap):
                    chains = [chains]
                nchains = len(chains)
                if isinstance(varnames, str):
                    varnames = [varnames]
                if varnames is slice(None, None, None):
                    varnames = self.varnames
                if len(varnames) == 1:
                    if nchains > 1:
                        result = ([_ifilter(iters, chain[varnames[0]]) for chain in chains])
                    else:
                        result = (_ifilter(iters, chains[0][varnames[0]]))
                else:
                    if nchains > 1:
                        return [Hashmap(**{varname:_ifilter(iters, chain[varname])
                                        for varname in varnames})
                                for chain in chains]
                    else:
                        return Hashmap(**{varname:_ifilter(iters, chains[0][varname]) for varname in varnames})
        else:
            raise IndexError('index not understood')
        
        return np.squeeze(result)
    
    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        else:
            a = [ch1==ch2 for ch1,ch2 in zip(other.chains, self.chains)]
            return all(a)
            
    def _allclose(self, other, **allclose_kw):
        try:
            self._assert_allclose(self, other, **allclose_kw)
        except AssertionError:
            return False
        return True
    
    def _assert_allclose(self, other, **allclose_kw):
        try:
            assert set(self.varnames) == set(other.varnames)
        except AssertionError:
            raise AssertionError('Variable names are different!\n'
                                 'self: {}\nother:{}'.format(
                                     self.varnames, other.varnames))
        assert isinstance(other, type(self))
        for ch1, ch2 in zip(self.chains, other.chains):
            for k,v in ch1.items():
                allclose_kw['err_msg'] = 'Failed on {}'.format(k)
                np.testing.assert_allclose(np.squeeze(v),
                                           np.squeeze(ch2[k]),
                                           **allclose_kw)
    
    def to_df(self):
        """
        Convert the trace object to a Pandas Dataframe
        """
        dfs = []
        outnames = self.varnames
        to_split = [name for name in outnames if len(self[name,0].shape)>1]
        for chain in self.chains:
            out = copy.deepcopy(chain)
            for split in to_split:
                records = np.squeeze(copy.deepcopy(chain[split]))
                n,k = records.shape[0:2]
                rest = records.shape[2:]
                if len(rest) == 0:
                    pass
                elif len(rest) == 1:
                    records = records.reshape(n,k*rest)
                else:
                    raise Exception("Parameter '{}' has too many dimensions"
                                    " to flatten able to be flattend?"               .format(split))
                records = ({split+'_'+str(i):record.T.tolist()
                            for i,record in enumerate(records.T)})
                out.update(records)
                del out[split]
            df = pd.DataFrame().from_dict({k:v
                                           for k,v in out.items()})
            dfs.append(df)
        if len(dfs) == 1:
            return dfs[0]
        else:
            return dfs

    def to_csv(self, filename, **pandas_kwargs):
        """
        Write trace out to file, going through Trace.to_df()
        
        If there are multiple chains in this trace, this will write
        them each out to 'filename_number.csv', where `number` is the
            number of the trace.
        """
        if 'index' not in pandas_kwargs:
            pandas_kwargs['index'] = False
        dfs = self.to_df()
        if isinstance(dfs, list):
            name, ext = os.path.splitext(filename)
            for i, df in enumerate(dfs):
                df.to_csv(name + '_' + str(i) + ext, **pandas_kwargs)
        else:
            dfs.to_csv(filename, **pandas_kwargs)
    
    @classmethod
    def from_df(cls, *dfs, varnames=None, combine_suffix='_'):
        """
        Convert a dataframe into a trace object
        """
        if len(dfs) > 1:
            traces = ([cls.from_df(df, varnames=varnames,
                        combine_suffix=combine_suffix) for df in dfs])
            return cls(*[trace.chains[0] for trace in traces])
        else:
            df = dfs[0]
        if varnames is None:
            varnames = df.columns
        unique_stems = []
        for col in varnames:
            suffix_split = col.split(combine_suffix)
            if suffix_split[0] == col:
                unique_stems.append(col)
            else:
                unique_stems.append('_'.join(suffix_split[:-1]))
        out = dict()
        for stem in set(unique_stems):
            cols = [var for var in df.columns if var.startswith(stem)]
            if len(cols) == 1:
                targets = df[cols].values.flatten().tolist()
            else:
                targets = [vec for vec in df[cols].values]
            out.update({stem:targets})
        return cls(**out)
    
    @classmethod
    def from_pymc3(cls, pymc3trace):
        try:
            from pymc3 import trace_to_dataframe
        except ImportError:
            raise ImportError("The 'trace_to_dataframe' function in "
                              "pymc3 is used for this feature. Pymc3 "
                              "failed to import.")
        return cls.from_df(mc.trace_to_dataframe(pymc3trace))
    
    @classmethod
    def from_csv(cls, filename=None, multi=False,
                      varnames=None, combine_suffix='_', **pandas_kwargs):
        """
        Read a CSV into a trace object, by way of `Trace.from_df()`
        """
        if multi:
            filepath = os.path.dirname(os.path.abspath(filename))
            filestem = os.path.basename(filename)
            targets = [f for f in os.listdir(filepath)
                         if f.startswith(filestem)]
            traces = ([cls.from_csv(filename=os.path.join(filepath, f)
                                    ,multi=False) for f in targets])
            if traces == []:
                raise FileNotFoundError("No such file or directory: " +
                                        filepath + filestem)
            return cls(*[trace.chains[0] for trace in traces])
        else:
            df = pd.read_csv(filename, **pandas_kwargs)
            return cls.from_df(df, varnames=varnames,
                               combine_suffix=combine_suffix)
    
    def plot(trace, burn=0, thin=None, varnames=None,
             kde_kwargs={}, trace_kwargs={}, figure_kwargs={}):
        f, ax = plot_trace(model=None, trace=trace, burn=burn,
                           thin=thin, varnames=varnames,
                      kde_kwargs=kde_kwargs, trace_kwargs=trace_kwargs,
                      figure_kwargs=figure_kwargs)
        return f,ax

####################
# HELPER FUNCTIONS #
####################

def _ifilter(filt,iterable):
    try:
        return iterable[filt]
    except:
        if isinstance(filt, (int, float)):
            filt = [filt]
        return [val for i,val in enumerate(iterable) if i in filt]

def _maybe_hashmap(*collections):
    out = []
    for collection in collections:
        if isinstance(collection, Hashmap):
            out.append(collection)
        else:
            out.append(Hashmap(**collection))
    return out

def _copy_hashmaps(*hashmaps):
    return [Hashmap(**{k:copy.deepcopy(v) for k,v in hashmap.items()})
            for hashmap in hashmaps]
