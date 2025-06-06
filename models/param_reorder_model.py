import json
import networkx as nx
import torch
import torch.nn as nn
import torch.optim as optim


class ParamOrderModel:
    def __init__(self, original_path, reordered_path, embedding_dim=64, lr=0.001, epochs=50):
        self.original_data = self.load_json(original_path)
        self.reordered_data = self.load_json(reordered_path)
        self.graph_original = self.build_graph(self.original_data)
        self.graph_reordered = self.build_graph(self.reordered_data)
        self.embedding_dim = embedding_dim
        self.epochs = epochs

        self.node_id_to_index = {node_id: idx for idx, node_id in enumerate(self.graph_original.nodes)}
        self.index_to_node_id = {idx: node_id for node_id, idx in self.node_id_to_index.items()}

        self.param_nodes_orig = self.get_ordered_parameters(self.graph_original)
        self.param_nodes_reord = self.get_ordered_parameters(self.graph_reordered)

        self.node_embedding = nn.Embedding(len(self.node_id_to_index), embedding_dim)
        self.model = self.OrderPredictionModel(embedding_dim)
        self.optimizer = optim.Adam(
            list(self.model.parameters()) + list(self.node_embedding.parameters()), lr=lr
        )
        self.loss_fn = nn.MSELoss()

    class OrderPredictionModel(nn.Module):
        def __init__(self, embedding_dim):
            super().__init__()
            self.fc = nn.Sequential(
                nn.Linear(embedding_dim, 128),
                nn.ReLU(),
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Linear(64, 1)  # prediktált pozíció
            )

        def forward(self, x):
            return self.fc(x).squeeze(-1)  # [num_params]

    def load_json(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def build_graph(self, data):
        G = nx.DiGraph()
        for node in data['nodes']:
            node_id = node['nodeId']
            attributes = node.copy()
            G.add_node(node_id, **attributes)
        for edge in data.get('edges', []):
            G.add_edge(edge['source'], edge['target'])
        return G

    def get_ordered_parameters(self, graph):
        params = []
        for node_id, data in graph.nodes(data=True):
            if data.get("class_") == "ParameterContext":
                params.append((data["start"], node_id))
        return [node_id for _, node_id in sorted(params)]

    def get_param_signature(self, graph, node_id):
        children = list(graph.successors(node_id))
        typename = name = None
        for child in children:
            data = graph.nodes[child]
            if data["class_"] == "TypeRefContext":
                for sub in graph.successors(child):
                    sub_data = graph.nodes[sub]
                    if sub_data["class_"] == "TerminalNodeImpl":
                        typename = sub_data.get("value")
            if data["class_"] == "NameContext":
                for sub in graph.successors(child):
                    sub_data = graph.nodes[sub]
                    if sub_data["class_"] == "TerminalNodeImpl":
                        name = sub_data.get("value")
        return typename, name

    def get_target_permutation(self):
        # Ez most: a reordered sorrend paramétereit nézzük (helyes sorrend),
        # és az original sig-ek indexeit kérjük le ebben a sorrendben
        reord_sigs = [self.get_param_signature(self.graph_reordered, nid) for nid in self.param_nodes_reord]
        orig_sigs = [self.get_param_signature(self.graph_original, nid) for nid in self.param_nodes_orig]

        positions = []
        for sig in orig_sigs:
            try:
                idx = reord_sigs.index(sig)
                positions.append(float(idx))
            except ValueError:
                raise ValueError(f"Nem található pár: {sig}")
        return torch.tensor(positions, dtype=torch.float32)

    def train(self):
        indices = torch.tensor([self.node_id_to_index[nid] for nid in self.param_nodes_orig], dtype=torch.long)
        targets = self.get_target_permutation()

        for epoch in range(self.epochs):
            self.optimizer.zero_grad()
            embeddings = self.node_embedding(indices)
            outputs = self.model(embeddings)
            loss = self.loss_fn(outputs, targets)
            loss.backward()
            self.optimizer.step()
            print(f"Epoch {epoch+1}, Loss: {loss.item():.4f}")

    def infer_permutation(self):
        indices = torch.tensor([self.node_id_to_index[nid] for nid in self.param_nodes_orig], dtype=torch.long)
        embeddings = self.node_embedding(indices)
        scores = self.model(embeddings)
        sorted_indices = torch.argsort(scores).tolist()
        return sorted_indices

    def process(self):
        self.train()
        predicted_order = self.infer_permutation()
        print(f"Predicted permutation: {predicted_order}")

        reordered_graph = self.graph_original.copy()
        param_nodes_orig = self.get_ordered_parameters(reordered_graph)
        reordered_param_nodes = [param_nodes_orig[i] for i in predicted_order]

        param_root = None
        for node_id, data in reordered_graph.nodes(data=True):
            if data.get("class_") in {"ParameterListContext", "NonEmptyParameterListContext"}:
                param_root = node_id
                break
        if param_root is None:
            raise ValueError("Nem található ParameterListContext a gráfban.")

        for child in list(reordered_graph.successors(param_root)):
            reordered_graph.remove_edge(param_root, child)

        def get_subtree_nodes(root):
            visited = set()
            stack = [root]
            while stack:
                node = stack.pop()
                if node not in visited:
                    visited.add(node)
                    stack.extend(reordered_graph.successors(node))
            return visited

        base_start = min(reordered_graph.nodes[nid]["start"] for nid in reordered_param_nodes) - 100
        new_starts = list(range(base_start, base_start + len(reordered_param_nodes) * 20, 20))
        new_commas = list(range(base_start + 10, base_start + len(reordered_param_nodes) * 20 - 10, 20))

        for i, node_id in enumerate(reordered_param_nodes):
            subtree_nodes = get_subtree_nodes(node_id)
            offset = new_starts[i] - reordered_graph.nodes[node_id]['start']
            for nid in subtree_nodes:
                reordered_graph.nodes[nid]['start'] += offset
            reordered_graph.add_edge(param_root, node_id)

            if i < len(reordered_param_nodes) - 1:
                comma_id = max(reordered_graph.nodes) + 1
                reordered_graph.add_node(comma_id, class_="TerminalNodeImpl", value=",", start=new_commas[i],
                                         label="syn", line=0, end=new_commas[i], nodeId=comma_id)
                reordered_graph.add_edge(param_root, comma_id)

        print("Reordering complete.")
        return reordered_graph


if __name__ == "__main__":
    from pretty_printer.pretty_printer import PrettyPrinter
    model = ParamOrderModel("control_generated.json", "control_reordered_generated.json", epochs=50)
    new_graph = model.process()

    print("Original graph:")
    pp = PrettyPrinter(model.graph_original)
    print(pp.get_script)

    print("Reordered graph (expected):")
    pp = PrettyPrinter(model.graph_reordered)
    print(pp.get_script)

    print("Reordered graph (actual):")
    pp = PrettyPrinter(new_graph)
    print(pp.get_script)
