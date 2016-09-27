from hlm import both as M
from hlm import utils
from hlm._constants import RTOL, ATOL, TEST_SEED, CLASSTYPES
from hlm.tests.utils import Model_Mixin, run_with_seed
from hlm.abstracts import Sampler_Mixin, Trace
import unittest as ut
import numpy as np
import pandas as pd
import os
import copy

FULL_PATH = os.path.dirname(os.path.abspath(__file__))

class Test_Generic(Model_Mixin, ut.TestCase):
    def setUp(self):
        Model_Mixin.build_self(self)
        self.cls = M.Generic
        instance = self.cls(**self.inputs, n_samples=0)
        self.answer_trace = Trace.from_csv(FULL_PATH + '/data/generic.csv')

    def test_mvcm(self):
        instance = self.cls(**self.inputs, n_samples=0)
        np.random.seed(TEST_SEED)
        instance.draw()
        other_answers = Trace.from_csv(FULL_PATH + '/data/mvcm.csv')
        strip_out = [col for col in instance.trace.varnames if col not in other_answers.varnames]
        other_answers._assert_allclose(instance.trace.drop(
                                       *strip_out, inplace=False))
    
    def test_membership_delta_mismatch(self):
        bad_D = np.ones(self.X.shape)
        try:
            self.cls(**self.inputs, n_samples=0)
        except UserWarning:
            pass
    
    def test_weights_mismatch(self):
        local_input = copy.deepcopy(self.inputs)
        local_input['W_'] = local_input['M']
        local_input['M'] = local_input['W']
        local_input['W'] = local_input['W_']
        try:
            self.cls(**local_input, n_samples=0)
        except (UserWarning, AssertionError):
            pass
    
    def test_missing_membership(self):
        local_input = copy.deepcopy(self.inputs)
        del local_input['membership']
        try:
            self.cls(**local_input, n_samples=0)
        except UserWarning:
            pass
