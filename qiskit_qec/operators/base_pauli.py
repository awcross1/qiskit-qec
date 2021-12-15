# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2020
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

# Part of the QEC framework

import numpy as np

from qiskit.quantum_info.operators.base_operator import BaseOperator
from qiskit.quantum_info.operators.mixins import AdjointMixin, MultiplyMixin

from qiskit_qec.linear.smatrix_api.smatrix import SMatrix

class BasePauli(BaseOperator, AdjointMixin, MultiplyMixin):
    def __init__(self, matrix, phase_exponent=0, stype='numpy'):
        print(f"matrix={matrix}")
        print(f"phase_exponent={phase_exponent}")
        self.sm = SMatrix.get_methods(stype=stype)
        self.matrix = SMatrix(self.sm.atleast_2d(matrix), stype=stype)
        self.stype = stype
        self.phase_exponent = phase_exponent
        super().__init__(num_qubits=self.matrix.shape[1]>>1)
    
    @property
    def num_paulis(self):
        return self.matrix.shape[0]

    def compose(self):
        pass

    def tensor(self):
        pass

    def expand(self):
        pass

    def _multiply(self):
        pass

    def conjugate(self):
        pass

    def transpose(self):
        pass