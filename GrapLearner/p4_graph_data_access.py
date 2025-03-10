import json
import networkx as nx
import pickle

from GrapLearner.graph_reader import GraphReader
from GrapLearner.graph_writer import GraphWriter


class P4GraphDataAccess(GraphReader, GraphWriter):
    def __init__(self):
        self._g = nx.DiGraph()

    def read_from_json(self, file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                for node in data['nodes']:
                    if 'value' not in node:
                        node['value'] = None
                    self._g.add_node(str(node['nodeId']), nodeId=int(node['nodeId']), line=int(node['line']), start=int(node['start']),
                                     end=int(node['end']), class_=node['class_'], value=node['value'])
                for edge in data['edges']:
                    self._g.add_edge(str(edge['source']), str(edge['target']))
        except AttributeError as e:
            print("Error: ", e)

    def read_from_pkl(self, file_path):
        try:
            with open("graph.pkl", "rb") as f:
                self._g = pickle.load(f)
        except Exception as e:
            print(e)

    def write_to_json(self, file_path):
        dictionary = {"nodes": [], "edges": []}
        for node in self._g.nodes:
            dictionary["nodes"].append(
                {"nodeId": self._g.nodes[node]["nodeId"],
                 "line": self._g.nodes[node]["line"],
                 "start": self._g.nodes[node]["start"],
                 "end": self._g.nodes[node]["end"],
                 "class_": self._g.nodes[node]["class_"],
                 "value": self._g.nodes[node]["value"]})
        for edge in self._g.edges:
            dictionary["edges"].append(
                {"source": edge[0], "target": edge[1]})
        try:
            with open(file_path, 'w') as f:
                json.dump(dictionary, f)
        except Exception as e:
            print(e)

    def write_to_pkl(self, file_path):
        with open(file_path, "wb") as f:
            pickle.dump(self._g, f)

    @property
    def get_graph(self):
        return self._g
