import networkx as nx
from gurobipy import Model, GRB, quicksum
from lib.Solver import Solver

class GurobiMIS(Solver):
    def __init__(self, G, params):
        self.G = G
        self.time_limit = params.get("time_limit", None)
        self.solution = {}
        self.model = None
        self.solution_time = None  # Initialize solution_time
        self.paths = []
        self.times = []

    def data_cb(self, model, where):
        if where == GRB.Callback.MIP:
            cur_obj = model.cbGet(GRB.Callback.MIP_OBJBST)

            self._stop_timer()
            if len(self.paths) == 0 or self.paths[-1] < cur_obj:
                self.times.append(self.solution_time)
                self.paths.append(cur_obj)

    def solve(self):
        # Create a new Gurobi model
        self.model = Model("Maximum_Independent_Set")

        # Set the time limit if specified
        if self.time_limit is not None:
            self.model.setParam("TimeLimit", self.time_limit)

        # Create a binary variable for each node
        node_vars = {
            node: self.model.addVar(vtype=GRB.BINARY, name=f"node_{node}")
            for node in self.G.nodes
        }

        # Add constraints: no two adjacent nodes can both be in the independent set
        for u, v in self.G.edges:
            if u != v:  # avoid adding a constraint for self-loops, if they exist
                self.model.addConstr(node_vars[u] + node_vars[v] <= 1, f"edge_{u}_{v}")

        # Set the objective: maximize the sum of the selected nodes
        self.model.setObjective(
            quicksum(node_vars[node] for node in self.G.nodes), GRB.MAXIMIZE
        )

        # Optimize the model
        self._start_timer()
        self.model.optimize(callback=self.data_cb)
        self.solution_time = self.model.Runtime
        # Check if a valid solution exists
        if self.model.status == GRB.OPTIMAL or self.model.status == GRB.TIME_LIMIT:
            self.solution["graph_mask"] = [
                int(node_vars[node].X) for node in self.G.nodes
            ]
            self.solution["size"] = sum(self.solution["graph_mask"])
            print(f"Maximum Independent Set size: {self.solution['size']}")
        else:
            print("No valid solution found.")
            self.solution["graph_mask"] = []
            self.solution["size"] = 0

        print(self.paths, self.times)

        # Optional: Output the variables if the solution was found
        if self.model.status == GRB.OPTIMAL:
            print("Nodes in the independent set:")
            for node in self.G.nodes:
                if node_vars[node].X > 0.5:  # effectively checking if the variable is 1
                    print(node)


if __name__ == "__main__":
    # Create a simple example graph
    G = nx.Graph()
    G.add_edges_from([(1, 2), (1, 3), (2, 3), (3, 4)])

    # Set parameters
    params = {"time_limit": 10}  # 10 seconds time limit

    # Initialize and solve the MIS problem
    solver = GurobiMIS(G, params)
    solver.solve()