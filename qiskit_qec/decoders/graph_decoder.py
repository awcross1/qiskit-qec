# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2019.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

# pylint: disable=invalid-name

"""
Decoders for quantum error correction codes, with a focus on those that can be
expressed as solving a graph-theoretic problem.
"""

import copy
import warnings
import retworkx as rx
import numpy as np

from qiskit import QuantumCircuit

try:
    from qiskit.providers.aer import Aer

    HAS_AER = True
except ImportError:
    from qiskit import BasicAer

    HAS_AER = False


class DecodingGraph:
    """
    Class to construct the graph corresponding to the possible syndromes
    of a quantum error correction code, and then run suitable decoders.
    """

    def __init__(self, code, S=None, brute=False):
        """
        Args:
            code (CodeCircuit): The QEC code circuit object for which this decoder
                will be used.
            brute (bool): If False, attempt to use custom method from code class.
        """

        self.code = code

        if S:
            self.S = S
        elif not brute and hasattr(code, "_get_all_processed_results"):
            self.S = self._make_syndrome_graph(results=code._get_all_processed_results())
        else:
            self.S = self._make_syndrome_graph()

    def _separate_string(self, string):

        separated_string = []
        for syndrome_type_string in string.split("  "):
            separated_string.append(syndrome_type_string.split(" "))
        return separated_string

    def string2nodes(self, string, logical="0"):
        """
        Generate probabilities of single error events from result counts.
        Args:
            string (string): Processed results string to convert.
            logical (string): Logical value whose results are used.
        Returns:
            dict: List of nodes corresponding to to the non-trivial
            elements in the string.
        """

        separated_string = self._separate_string(string)
        nodes = []
        for syn_type, _ in enumerate(separated_string):
            for syn_round in range(len(separated_string[syn_type])):
                elements = separated_string[syn_type][syn_round]
                for elem_num, element in enumerate(elements):
                    if (syn_type == 0 and element != logical) or (syn_type != 0 and element == "1"):
                        if syn_type == 0:
                            elem_num = syn_round
                            syn_round = 0
                        node = {"time": syn_round, "is_logical": syn_type == 0, "element": elem_num}
                        nodes.append(node)
        return nodes

    def _make_syndrome_graph(self, results=None):

        S = rx.PyGraph(multigraph=False)
        if results:

            for string in results:
                nodes = self.string2nodes(string)
                for node in nodes:
                    if node not in S.nodes():
                        S.add_node(node)
                for source in nodes:
                    for target in nodes:
                        if target != source:
                            n0 = S.nodes().index(source)
                            n1 = S.nodes().index(target)
                            S.add_edge(n0, n1, 1)

        else:
            qc = self.code.circuit["0"]

            blank_qc = QuantumCircuit()
            for qreg in qc.qregs:
                blank_qc.add_register(qreg)
            for creg in qc.cregs:
                blank_qc.add_register(creg)

            error_circuit = {}
            circuit_name = {}
            depth = len(qc)
            for j in range(depth):
                gate = qc.data[j][0].name
                qubits = qc.data[j][1]
                if gate not in ["measure", "reset"]:
                    for error in ["x", "y", "z"]:
                        for qubit in qubits:
                            temp_qc = copy.deepcopy(blank_qc)
                            temp_qc.name = str((j, qubit, error))
                            temp_qc.data = qc.data[0:j]
                            getattr(temp_qc, error)(qubit)
                            temp_qc.data += qc.data[j : depth + 1]
                            circuit_name[(j, qubit, error)] = temp_qc.name
                            error_circuit[temp_qc.name] = temp_qc
                elif gate == "measure":
                    pre_error = "x"
                    for post_error in ["id", "x"]:
                        for qubit in qubits:
                            temp_qc = copy.deepcopy(blank_qc)
                            temp_qc.name = str((j, qubit, pre_error + "_" + post_error))
                            temp_qc.data = qc.data[0:j]
                            getattr(temp_qc, pre_error)(qubit)
                            temp_qc.data.append(qc.data[j])
                            getattr(temp_qc, post_error)(qubit)
                            temp_qc.data += qc.data[j + 1 : depth + 1]
                            circuit_name[(j, qubit, pre_error + "_" + post_error)] = temp_qc.name
                            error_circuit[temp_qc.name] = temp_qc

            if HAS_AER:
                simulator = Aer.get_backend("aer_simulator")
            else:
                simulator = BasicAer.get_backend("qasm_simulator")

            job = simulator.run(list(error_circuit.values()), shots=1)

            node_map = {}
            for j in range(depth):
                gate = qc.data[j][0].name
                qubits = qc.data[j][1]
                errors = ["x", "y", "z"] * (gate not in ["reset", "measure"]) + ["x_id", "x_x"] * (
                    gate == "measure"
                )
                for error in errors:
                    for qubit in qubits:
                        raw_results = {}
                        raw_results["0"] = job.result().get_counts(str((j, qubit, error)))
                        results = self.code.process_results(raw_results)["0"]

                        for string in results:

                            nodes = self.string2nodes(string)

                            assert len(nodes) in [0, 2], (
                                "Error of type "
                                + error
                                + " on qubit "
                                + str(qubit)
                                + " at depth "
                                + str(j)
                                + " creates "
                                + str(len(nodes))
                                + " nodes in syndrome graph, instead of 2."
                            )
                            for node in nodes:
                                if node not in node_map.values():
                                    node_map[S.add_node(node)] = node
                            for source in nodes:
                                for target in nodes:
                                    if target != source:
                                        ns = list(node_map.keys())[
                                            list(node_map.values()).index(source)
                                        ]
                                        nt = list(node_map.keys())[
                                            list(node_map.values()).index(target)
                                        ]
                                        S.add_edge(ns, nt, 1)

        return S

    def get_error_probs(self, results, logical="0", use_old=False):
        """
        Generate probabilities of single error events from result counts.
        Args:
            results (dict): A results dictionary, as produced by the
            `process_results` method of the code.
            logical (string): Logical value whose results are used.
            use_old (bool): Whether to use the old calculation method.
        Returns:
            dict: Keys are the edges for specific error
            events, and values are the calculated probabilities
        Additional information:
            Uses `results` to estimate the probability of the errors that
            create the pairs of nodes specified by the edge.
            Default calculation method is that of Spitz, et al.
            https://doi.org/10.1002/qute.201800012
        """

        if not use_old:

            results = results[logical]
            shots = sum(results.values())

            neighbours = {}
            av_v = {}
            for n in self.S.node_indexes():
                av_v[n] = 0
                neighbours[n] = []

            av_vv = {}
            av_xor = {}
            for n0, n1 in self.S.edge_list():
                av_vv[n0, n1] = 0
                av_xor[n0, n1] = 0
                neighbours[n0].append(n1)
                neighbours[n1].append(n0)

            for string in results:

                # list of i for which v_i=1
                error_nodes = self.string2nodes(string, logical=logical)

                for node0 in error_nodes:
                    n0 = self.S.nodes().index(node0)
                    av_v[n0] += results[string]
                    for n1 in neighbours[n0]:
                        node1 = self.S[n1]
                        if node1 in error_nodes and (n0, n1) in av_vv:
                            av_vv[n0, n1] += results[string]
                        if node1 not in error_nodes:
                            if (n0, n1) in av_xor:
                                av_xor[n0, n1] += results[string]
                            else:
                                av_xor[n1, n0] += results[string]

            for n in self.S.node_indexes():
                av_v[n] /= shots
            for n0, n1 in self.S.edge_list():
                av_vv[n0, n1] /= shots
                av_xor[n0, n1] /= shots

            boundary = []
            error_probs = {}
            for n0, n1 in self.S.edge_list():

                if self.S[n0]["is_logical"]:
                    boundary.append(n1)
                elif self.S[n1]["is_logical"]:
                    boundary.append(n0)
                else:
                    if (1 - 2 * av_xor[n0, n1]) != 0:
                        x = (av_vv[n0, n1] - av_v[n0] * av_v[n1]) / (1 - 2 * av_xor[n0, n1])
                        error_probs[n0, n1] = max(0, 0.5 - np.sqrt(0.25 - x))
                    else:
                        error_probs[n0, n1] = np.nan

            prod = {}
            for n0 in boundary:
                for n1 in self.S.node_indexes():
                    if n0 != n1:
                        if n0 not in prod:
                            prod[n0] = 1
                        if (n0, n1) in error_probs:
                            prod[n0] *= 1 - 2 * error_probs[n0, n1]
                        elif (n1, n0) in error_probs:
                            prod[n0] *= 1 - 2 * error_probs[n1, n0]

            for n0 in boundary:
                error_probs[n0, n0] = 0.5 + (av_v[n0] - 0.5) / prod[n0]

        else:

            results = results[logical]
            shots = sum(results.values())

            count = {
                element: {edge: 0 for edge in self.S.edge_list()}
                for element in ["00", "01", "10", "11"]
            }

            for string in results:

                nodes = self.string2nodes(string, logical=logical)

                for edge in self.S.edge_list():
                    element = ""
                    for j in range(2):
                        if self.S[edge[j]] in nodes:
                            element += "1"
                        else:
                            element += "0"
                    count[element][edge] += results[string]

            error_probs = {}
            for edge in self.S.edge_list():
                ratios = []
                for elements in [("00", "11"), ("11", "00"), ("01", "10"), ("10", "01")]:
                    if count[elements[1]][edge] > 0:
                        ratio = count[elements[0]][edge] / count[elements[1]][edge]
                        ratios.append(ratio)
                ratio = min(ratios)
                e0 = self.S[edge[0]]
                e1 = self.S[edge[1]]
                if e1[0] == 0:
                    e1 = e0
                if e0[0] == 0:
                    e0 = e1
                if (e0, e1) in error_probs:
                    error_probs[e0, e1] = max(ratio / (1 + ratio), error_probs[e0, e1])
                else:
                    error_probs[e0, e1] = ratio / (1 + ratio)

        return error_probs

    def weight_syndrome_graph(self, results):
        """Generate weighted syndrome graph from result counts.

        Args:
            results (dict): A results dictionary, as produced by the
            `process_results` method of the code.

        Additional information:
            Uses `results` to estimate the probability of the errors that
            create the pairs of nodes in S. The edge weights are then
            replaced with the corresponding -log(p/(1-p).
        """

        error_probs = self.get_error_probs(results)

        for edge in self.S.edge_list():
            p = error_probs[self.S[edge[0]], self.S[edge[1]]]
            if p == 0:
                w = np.inf
            elif 1 - p == 1:
                w = -np.inf
            else:
                w = -np.log(p / (1 - p))
            self.S.update_edge(edge[0], edge[1], w)

    def make_error_graph(self, string):
        """
        Args:
            string (str): A string describing the output from the code.

        Returns:
            E: The subgraph of S which corresponds to the non-trivial
            syndrome elements in the given string.
        """

        E = rx.PyGraph(multigraph=False)
        separated_string = self._separate_string(string)
        for syndrome_type, _ in enumerate(separated_string):
            for syndrome_round in range(len(separated_string[syndrome_type])):
                elements = separated_string[syndrome_type][syndrome_round]
                for elem_num, element in enumerate(elements):
                    if element == "1" or syndrome_type == 0:
                        if syndrome_type == 0:
                            elem_num = syndrome_round
                            syndrome_round = 0
                        node = {
                            "time": syndrome_round,
                            "is_logical": syndrome_type == 0,
                            "element": elem_num,
                        }
                        if node not in E.nodes():
                            E.add_node(node)

        # for each pair of nodes in error create an edge and weight with the
        # distance
        distance_matrix = rx.graph_floyd_warshall_numpy(self.S, weight_fn=float)

        for source_index in E.node_indexes():
            for target_index in E.node_indexes():
                source = E[source_index]
                target = E[target_index]
                if target != source:
                    distance = int(
                        distance_matrix[self.S.nodes().index(source)][self.S.nodes().index(target)]
                    )
                    E.add_edge(source_index, target_index, -distance)
        return E


class GraphDecoder:
    """
    Class to construct the graph corresponding to the possible syndromes
    of a quantum error correction code, and then run suitable decoders.
    """

    def __init__(self, graph):
        """
        Args:
            graph (GraphDecoder): The decoder graph on which decoding is performed.
        """

        self.graph = graph

    def matching(self, string):
        """
        Args:
            string (str): A string describing the output from the code.

        Returns:
            str: A string with corrected logical values,
                computed using minimum weight perfect matching.

        Additional information:
            This function can be run directly, or used indirectly to
            calculate a logical error probability with `get_logical_prob`
        """

        # this matching algorithm is designed for a single graph
        E = self.graph.make_error_graph(string)

        # set up graph that is like E, but each syndrome node is connected to a
        # separate copy of the nearest logical node
        E_matching = rx.PyGraph(multigraph=False)
        syndrome_nodes = []
        logical_nodes = []
        logical_neighbours = []
        for node in E.nodes():
            E_matching.add_node(node)
            if node["is_logical"]:
                logical_nodes.append(node)
            else:
                syndrome_nodes.append(node)
        for source in syndrome_nodes:
            n0 = E.nodes().index(source)
            for target in syndrome_nodes:
                n1 = E.nodes().index(target)
                if target != source:
                    E_matching.add_edge(
                        n0,
                        n1,
                        E.get_edge_data(n0, n1),
                    )

            potential_logical = {}
            for target in logical_nodes:
                n1 = E.nodes().index(target)
                potential_logical[n1] = E.get_edge_data(n0, n1)
            nearest_logical = max(potential_logical, key=potential_logical.get)
            nl_target = E[nearest_logical].copy()
            nl_target["connected_to"] = source.copy()
            if nl_target not in E_matching.nodes():
                E_matching.add_node(nl_target)
            E_matching.add_edge(
                n0,
                E_matching.nodes().index(nl_target),
                potential_logical[nearest_logical],
            )
            logical_neighbours.append(nl_target)
        for source in logical_neighbours:
            for target in logical_neighbours:
                if target != source:
                    n0 = E_matching.nodes().index(source)
                    n1 = E_matching.nodes().index(target)
                    E_matching.add_edge(n0, n1, 0)
        # do the matching on this
        matches = rx.max_weight_matching(E_matching, max_cardinality=True, weight_fn=lambda x: x)
        # use it to construct and return a corrected logical string
        logicals = self.graph._separate_string(string)[0]
        for (n0, n1) in matches:
            source = E_matching[n0]
            target = E_matching[n1]
            sil = E_matching[n0]["is_logical"]
            til = E_matching[n1]["is_logical"]
            if sil and not til:
                elem = E_matching[n0]["element"]
                logicals[elem] = str((int(logicals[elem]) + 1) % 2)
            if til and not sil:
                elem = E_matching[n1]["element"]
                logicals[elem] = str((int(logicals[elem]) + 1) % 2)

        logical_string = ""
        for logical in logicals:
            logical_string += logical + " "
        logical_string = logical_string[:-1]

        return logical_string

    def get_logical_prob(self, results, algorithm="matching"):
        """
        Args:
            results (dict): A results dictionary, as produced by the
            `process_results` method of the code.
            algorithm (str): Choice of which decoder to use.

        Returns:
            dict: Dictionary of logical error probabilities for
            each of the encoded logical states whose results were given in
            the input.
        """

        logical_prob = {}
        for log in results:

            shots = 0
            incorrect_shots = 0

            corrected_results = {}
            if algorithm == "matching":
                for string in results[log]:
                    corr_str = self.matching(string)
                    if corr_str in corrected_results:
                        corrected_results[corr_str] += results[log][string]
                    else:
                        corrected_results[corr_str] = results[log][string]
            else:
                warnings.warn(
                    "The requested algorithm " + str(algorithm) + " is not known.",
                    Warning,
                )

            for string, samples in corrected_results.items():
                shots += samples
                if string[0] != str(log):
                    incorrect_shots += samples

            logical_prob[log] = incorrect_shots / shots

        return logical_prob