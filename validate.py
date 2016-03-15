from rpy2.robjects import r as R
from warnings import warn as Warn 
import numpy as np
from numpy.testing import assert_allclose
import matplotlib.pyplot as plt

prec = {}
pdict = {}
def assert_Rarray_allclose(array, R_name):
    N, J = array.shape
    for i in range(N):
        ri = i+1
        Rvect = R("{n}[{ri},]".format(n=R_name, ri=ri))
        Pyvect = array[i,:]
        assert_allclose(Rvect, Pyvect, err_msg="Row {} not equal".format(i))

def stepdown_precision(a1, a2, rtol = 7, err_msg=''):
    while True:
        try:
            assert_allclose(a1, a2, rtol=10**(-1 * rtol), err_msg=err_msg)
            break
        except AssertionError:
            rtol -= 1
    return rtol

def to_R(array, name, keep_shape=True):
    #don't forget R is column-major...
    vect = "c({})".format(','.join([str(x) for x in array.T.flatten()]))
    R("{n} <- {v}".format(n=name, v=vect))
    if keep_shape and len(array.shape) > 1:
        R("dim({n}) <- c{s}".format(s=array.shape, n=name))
    return R("{n}".format(n=name))

def test_Betas(s):
    R('source("mcmc/betas.R")')
    R_mBetas, R_vBetas = R('mBetas'), R('vBetas')
    if s.step == 0:
        s.__next__()
    else:
        Warn('Sampler is not in Beta step, cowardly refusing to step')
    m_betas, v_betas = s.trace.Derived['m_betas'], s.trace.Derived['v_betas']
    mprec = stepdown_precision(m_betas, R_mBetas, err_msg =  "Mean vectors do not match")
    vprec = stepdown_precision(v_betas, R_vBetas, err_msg = "Covariance Matrices do not match")
    #print("R & Python parameters match, using Python RV")
    new_betas = s.trace.front()['betas']
    
    to_R(new_betas, "betas")
    R("tbetas <- betas")
    R("betas <- t(betas)")
    R("Betas[i,] <- t(betas)")
    #return R_mBetas, R_vBetas, m_betas, v_betas, new_betas, R("betas")
    return mprec, vprec

def test_Thetas(s):
    R('source("mcmc/thetas.R")')
    R_mU, R_vU = R('mU'), R('vU')
    if s.step == 1:
        s.__next__()
    else:
        Warn('Sampler is not in Theta step, cowardly refusing to step')
    m_thetas, v_thetas = s.trace.Derived['m_u'], s.trace.Derived['v_u']
    mprec = stepdown_precision(m_thetas, R_mU, err_msg = "Mean vectors do not match")
    vprec = stepdown_precision(v_thetas, R_vU, err_msg = "Covariance Matrices do not match")
    #print("R & Python parameters match, using Python RV")
    new_thetas = s.trace.front()['thetas']

    to_R(new_thetas, "us")
    R("Us[i,] <- us")
    #return R_mU, R_vU, m_thetas, v_thetas, new_thetas, R("us")
    return mprec, vprec

def test_Sigma_e(s):
    R('source("mcmc/sigma_e.R")')
    R_de = R('de')
    if s.step == 2:
        s.__next__()
    else:
        Warn('Sampler is not in sigma_e step, cowardly refusing to step')
    de = s.trace.Derived['de']
    deprec = stepdown_precision(de, R_de, err_msg= "Shape parameter does not match")
    #print("R & Python parameters match, using Python RV")
    new_sigma_e = s.trace.front()['sigma_e']

    to_R(new_sigma_e, "new_sigma2e")
    R("sigma2e[i] <- new_sigma2e")
    #return s.trace.Statics['ce'], de, R('ce'), R('de'), new_sigma_e, R('new_sigma2e')
    return deprec

def test_Sigma_u(s):
    R('source("mcmc/sigma_u.R")')
    R_bu = R('bu')
    if s.step == 3:
        s.__next__()
    else:
        Warn('Sampler is not in sigma_u step, cowardly refusing to step')
    bu = s.trace.Derived['bu']
    buprec = stepdown_precision(bu, R_bu, err_msg="Shape parameter does not match")
    #print("R & Python parameters match, using Python RV")
    new_sigma_u = s.trace.front()['sigma_u']

    to_R(new_sigma_u, "new_sigma2u")
    R("sigma2u[i] <- new_sigma2u")
    #return s.trace.Statics['au'], bu, R('au'), R('bu'),new_sigma_u,R('new_sigma2u')
    return buprec

def test_Rho(s, pdict=pdict):
    R('source("mcmc/rho.R")')
    if s.step == 4:
        s.__next__()
    else:
        Warn('Sampler is not in rho step, cowardly refusing to step')
    density = s.trace.Derived['norm_den']
    cdist = s.trace.Derived['cdist']
    pdfprec = stepdown_precision(density.flatten(), R('norm_den'), err_msg="Standardized density mismatch")
    cdfprec = stepdown_precision(cdist.flatten(), R('cumu_den'), err_msg="Cumulative density mismatch")
    #print("R & Python distributions match, using Python RV")
    new_rho_rval = s.trace.front('rho')

    R("new_rho <- {}".format(new_rho_rval[0]))
    R("rho[i] <- new_rho")
    pdict['rho']['r'].append(list(R("norm_den")))
    pdict['rho']['py'].append(list(s.trace.Derived['norm_den'].flatten().tolist()))
    #return density, cdist, new_rho_rval
    return pdfprec, cdfprec

def test_Lambda(s, pdict=pdict):
    R('source("mcmc/lambda.R")')
    if s.step == 5:
        s.__next__()
    else:
        Warn('Sampler is not in rho step, cowardly refusing to step')
    density = s.trace.Derived['norm_den']
    cdist = s.trace.Derived['cdist']
    pdfprec = stepdown_precision(density.flatten(), R('norm_den'), err_msg="Standardized density mismatch")
    cdfprec = stepdown_precision(cdist.flatten(), R('cumu_den'), err_msg="Cumulative density mismatch")
    #print("R & Python distributions match, using Python RV")
    new_lambda_rval = s.trace.front('lam')

    #to_R(new_rho_rval, "new_lambda")
    R("new_lambda <- {}".format(new_lambda_rval[0]))
    R("lambda[i] <- new_lambda")
    #return density, cdist, new_lambda_rval
    norm_den = s.trace.Derived['norm_den'].flatten()
    pdict['lambda']['r'].append(list(R("norm_den")))
    pdict['lambda']['py'].append(list(s.trace.Derived['norm_den'].flatten().tolist()))
    return pdfprec, cdfprec

def test_Iteration(s, plots=pdict, precision=prec):
    precision['betas'].append(test_Betas(s))
    #print("beta precision: {}".format(precision['betas'][-1]))
    precision['thetas'].append(test_Thetas(s))
    #print("theta precision: {}".format(precision['thetas'][-1]))
    precision['sigma_e'].append(test_Sigma_e(s))
    #print("sigma_e precision: {}".format(precision['sigma_e'][-1]))
    precision['sigma_u'].append(test_Sigma_u(s))
    #print("sigma_u precision: {}".format(precision['sigma_u'][-1]))
    precision['rho'].append(test_Rho(s,  pdict=plots))
    #print("rho precision: {}".format(precision['rho'][-1]))
    precision['lambda'].append(test_Lambda(s, pdict=plots))
    #print("lambda precision: {}".format(precision['lambda'][-1]))
    R("i <- i + 1")

if __name__ == "__main__":
    import setup as HSAR
    import validate as v
    
    pdict = {'lambda':{'r':[],"py":[]}, 'rho':{'r':[], 'py':[]}}
    prec = {'lambda':[], 'rho':[], 'betas':[], 'thetas':[], 'sigma_e':[],'sigma_u':[]}
    s = HSAR.setup_HSAR()
    R("source('setup.R')")
    to_R(s.trace.Statics['rhos'], 'detval')
    to_R(s.trace.Statics['lambdas'], 'detvalM')
    R("i<-2")
    
    test_Iteration(s, pdict=pdict, prec=prec)


    