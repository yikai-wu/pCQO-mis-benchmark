import torch
from torch.func import grad, vmap

import networkx as nx
from networkx import Graph

import torch.optim as optim

import time
from lib.Solver import Solver


# def loss_function(
#     Matrix_X, adjacency_matrix_tensor, adjacency_matrix_tensor_comp, gamma, beta
# ):

#     summed_weights = Matrix_X.sum()

#     second_term = (gamma / 2) * (Matrix_X.T @ (adjacency_matrix_tensor) @ Matrix_X)

#     third_term = (beta / 2) * ((Matrix_X.T @ (adjacency_matrix_tensor_comp)) @ Matrix_X)

#     loss = -summed_weights + second_term - third_term

#     return loss

def loss_function(
    Matrix_X, adjacency_matrix_tensor, gamma, beta
):

    summed_weights = Matrix_X.sum()

    second_term = (gamma / 2) * (Matrix_X.T @ (adjacency_matrix_tensor) @ Matrix_X)

    loss = -summed_weights + second_term

    return loss

def normalize_adjacency_matrix(graph):
    # Get the adjacency matrix
    adjacency_matrix = nx.adjacency_matrix(graph).todense()

    # Convert to PyTorch tensor        adjacency_matrix_tensor_comp = adjacency_matrix_comp_dense.to(device)
    adjacency_matrix = torch.Tensor(adjacency_matrix)

    # Calculate the degree matrix
    degree_matrix = torch.diag(torch.tensor(list(dict(graph.degree()).values())))

    # Normalize the adjacency matrix
    normalized_adjacency = (
        torch.inverse(torch.sqrt(degree_matrix))
        @ adjacency_matrix
        @ torch.inverse(torch.sqrt(degree_matrix)).to_dense()
    )

    return normalized_adjacency


class Quadratic_Batch(Solver):
    def __init__(self, G: Graph, params):
        super().__init__()

        self.learning_rate = params.get("learning_rate", 0.001)

        self.number_of_steps = params.get("number_of_steps", 10000)

        self.graph = G

        self.beta = params.get("beta", 1)

        self.gamma = params.get("gamma", 625)

        self.batch_size = params.get("batch_size", 256)

        self.steps_per_batch = params.get("steps_per_batch", 350)

        self.output_interval = params.get("output_interval", self.steps_per_batch)

        self.graphs_per_optimizer = params.get("graphs_per_optimizer", 128)

        self.threshold = params.get("threshold", 0.0)

        self.seed = 113

        self.graph_order = len(G.nodes)

        self.solution = {}

        self.normalize = params.get("normalize", False)

        self.combine = params.get("combine", False)

        self.value_initializer = torch.nn.init.uniform_

        self.test_runtime = params.get("test_runtime", False)

        self.save_sample_path = params.get("save_sample_path", False)
        
        self.adam_beta_1 = params.get("adam_beta_1", 0.9)

        self.adam_beta_2 = params.get("adam_beta_2", 0.999)

    def solve(self):
        # Obtain A_G and A_G hat (and/or N_G and N_G hat)

        self._start_timer()

        if not self.normalize or self.combine:
            adjacency_matrix_dense = torch.Tensor(
                nx.adjacency_matrix(self.graph).todense()
            ).to_dense()
            adjacency_matrix_comp_dense = torch.Tensor(
                nx.adjacency_matrix(nx.complement(self.graph)).todense()
            ).to_dense()
        if self.normalize or self.combine:
            normalized_adjacency_matrix_dense = normalize_adjacency_matrix(self.graph)
            normalized_adjacency_matrix_comp_dense = normalize_adjacency_matrix(
                nx.complement(self.graph)
            )
        if self.combine:
            adjacency_matrix_dense = torch.stack(
                (adjacency_matrix_dense, normalized_adjacency_matrix_dense), dim=0
            )
            adjacency_matrix_comp_dense = torch.stack(
                (adjacency_matrix_comp_dense, normalized_adjacency_matrix_comp_dense),
                dim=0,
            )
        elif self.normalize:
            adjacency_matrix_dense = normalized_adjacency_matrix_dense
            adjacency_matrix_comp_dense = normalized_adjacency_matrix_comp_dense

        # Optimization loop:
        # Initialization:
        torch.manual_seed(self.seed)

        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        print("using device: ", device)

        Matrix_X = torch.empty((self.batch_size, self.graph_order))

        for batch in range(self.batch_size):
            Matrix_X.data[batch, :] = self.value_initializer(
                torch.empty((self.graph_order))
            )

        Matrix_X = Matrix_X.to(device)

        Matrix_X = Matrix_X.requires_grad_(True)

        gamma = torch.tensor(self.gamma, device=device)

        beta = torch.tensor(self.beta, device=device)

        learning_rate_alpha = self.learning_rate

        number_of_iterations_T = self.number_of_steps

        adjacency_matrix_tensor = adjacency_matrix_dense.to(device)
        adjacency_matrix_tensor_comp = adjacency_matrix_comp_dense.to(device)

        # Define Optimizer over matrix X
        with torch.no_grad():
            parts = torch.split(Matrix_X, self.graphs_per_optimizer)

        optimizers = []

        for part in parts:
            optimizers.append(optim.Adam([part], learning_rate_alpha, betas=(self.adam_beta_1, self.adam_beta_2)))

        # optimizer = optim.Adam(parts, lr=learning_rate_alpha)
        # optimizer2 = optim.Adam([part_two], lr=learning_rate_alpha)

        best_MIS = 0
        MIS = []

        zero_grad_time_cum = 0
        per_sample_grad_time_cum = 0
        optim_step_time_cum = 0
        box_constraint_time_cum = 0
        is_check_time_cum = 0
        restart_time_cum = 0

        initializations_solved = 0


        if self.save_sample_path:
            solution_path = []
            solution_times = []

        output_tensors = []

        steps_to_best_MIS = 0

        per_sample_grad_funct = vmap(
            grad(loss_function), in_dims=(0, None, None, None) #, None)
        )

        if device == "cuda:0":
            torch.cuda.synchronize()

        for iteration_t in range(number_of_iterations_T):

            if self.test_runtime:
                start_time = time.time()

            for optimizer in optimizers:
                optimizer.zero_grad()

            if self.test_runtime:
                torch.cuda.synchronize()
                zero_grad_time = time.time()
                zero_grad_time_cum += zero_grad_time - start_time

            per_sample_gradients = torch.split(
                per_sample_grad_funct(
                    Matrix_X,
                    adjacency_matrix_tensor,
                    # adjacency_matrix_tensor_comp,
                    gamma,
                    beta,
                ),
                self.graphs_per_optimizer,
            )

            with torch.no_grad():
                for i, part in enumerate(parts):
                    part.grad = per_sample_gradients[i]

            if self.test_runtime:
                torch.cuda.synchronize()
                per_sample_gradient_time = time.time()
                per_sample_grad_time_cum += per_sample_gradient_time - zero_grad_time

            for optimizer in optimizers:
                optimizer.step()

            if self.test_runtime:
                torch.cuda.synchronize()
                optim_step_time = time.time()
                optim_step_time_cum += optim_step_time - per_sample_gradient_time

            # Box-constraining:
            Matrix_X.data[Matrix_X >= 1] = 1
            Matrix_X.data[Matrix_X <= 0] = 0

            if self.test_runtime:
                torch.cuda.synchronize()
                box_constraint_time = time.time()
                box_constraint_time_cum += box_constraint_time - optim_step_time

            if (iteration_t + 1) % self.steps_per_batch == 0:

                # masks = Matrix_X.data[:, :] > self.threshold

                # for mask in masks:
                #     indices = mask.nonzero(as_tuple=True)[0].tolist()
                #     subgraph = self.graph.subgraph(indices)
                #     local_IS = indices

                #     # If no MIS, move on
                #     # if MIS_checker(MIS, G)[0] is False: MIS = []
                #     if any(subgraph.edges()):
                #         local_IS = []

                #     IS_length = len(local_IS)

                #     if IS_length > best_MIS:
                #         steps_to_best_MIS = iteration_t
                #         best_MIS = IS_length
                #         MIS = local_IS

                masks = Matrix_X.data[:,:].bool().float().clone()
                output_tensors.append(masks)
                n = self.graph_order

                masks = masks.to(device)

                indices_to_replace = []

                for batch_id, X_torch_binarized in enumerate(masks):
                    if X_torch_binarized.sum() != 0 and (X_torch_binarized.T @ adjacency_matrix_tensor @ X_torch_binarized) == 0:
                        # we have an IS. Next, we check if this IS is maximal based on the proof of the second theorem: Basically, we are checking if it is a local min based on the fixed point definition:
                        # if for some gradient update, we are still at the boundary, then we have maximal IS
                        X_torch_binarized_update = X_torch_binarized - 0.1*(-torch.ones(n, device=device) + (n*adjacency_matrix_tensor - adjacency_matrix_tensor_comp)@X_torch_binarized)
                        # Projection to [0,1]
                        X_torch_binarized_update[X_torch_binarized_update>=1] =1
                        X_torch_binarized_update[X_torch_binarized_update<=0] =0
                        if torch.equal(X_torch_binarized, X_torch_binarized_update):
                            initializations_solved += 1
                            indices_to_replace.append(batch_id)
                            # we have a maximal IS:
                            MIS = torch.nonzero(X_torch_binarized).squeeze()
                            # Exit the function with True
                            if len(MIS) > best_MIS:
                                steps_to_best_MIS = iteration_t+1
                                best_MIS = len(MIS)
                                MIS = MIS
                
                if self.test_runtime:
                    torch.cuda.synchronize()
                    IS_check_time = time.time()
                    is_check_time_cum += IS_check_time - box_constraint_time

                if self.save_sample_path:
                    self._stop_timer()
                    solution_path.append(best_MIS)
                    solution_times.append(self.solution_time)

                # # Restart X and the optimizer to search at a different point in [0,1]^n
                with torch.no_grad():
                    for batch in range(self.batch_size):
                        Matrix_X.data[batch, :] = self.value_initializer(
                            torch.empty((self.graph_order))
                        )
                        Matrix_X = Matrix_X.to(device).requires_grad_(True)

                if self.test_runtime:
                    torch.cuda.synchronize()
                    restart_time = time.time()
                    restart_time_cum += restart_time - IS_check_time

            if (iteration_t + 1) % self.output_interval == 0:
                print(
                    f"Step {iteration_t + 1}/{number_of_iterations_T}, IS: {MIS}, lr: {learning_rate_alpha}, MIS Size: {best_MIS}"
                )

        # n = self.graph_order
        # for output_tensor in output_tensors:
        #     for batch_id, X_torch_binarized in enumerate(output_tensor):
        #         if X_torch_binarized.sum() != 0 and (X_torch_binarized.T @ adjacency_matrix_tensor @ X_torch_binarized) == 0:
        #             # we have an IS. Next, we check if this IS is maximal based on the proof of the second theorem: Basically, we are checking if it is a local min based on the fixed point definition:
        #             # if for some gradient update, we are still at the boundary, then we have maximal IS
        #             X_torch_binarized_update = X_torch_binarized - 0.1*(-torch.ones(n, device=device) + (n*adjacency_matrix_tensor - adjacency_matrix_tensor_comp)@X_torch_binarized)
        #             # Projection to [0,1]
        #             X_torch_binarized_update[X_torch_binarized_update>=1] =1
        #             X_torch_binarized_update[X_torch_binarized_update<=0] =0
        #             if torch.equal(X_torch_binarized, X_torch_binarized_update):
        #                 initializations_solved += 1
        #                 indices_to_replace.append(batch_id)
        #                 # we have a maximal IS:
        #                 MIS = torch.nonzero(X_torch_binarized).squeeze()
        #                 # Exit the function with True
        #                 if len(MIS) > best_MIS:
        #                     steps_to_best_MIS = iteration_t+1
        #                     best_MIS = len(MIS)
        #                     MIS = MIS

        if device == "cuda:0":
            torch.cuda.synchronize()
        self._stop_timer()

        if self.save_sample_path:
            print(solution_path, solution_times)

        print(f"Steps to best MIS: {steps_to_best_MIS}")

        if self.test_runtime:
            print(f"Total time spent zero-ing gradients: {zero_grad_time_cum}")
            print(f"Total time spent computing per-sample gradients: {per_sample_grad_time_cum}")
            print(f"Total time spent taking optimizer steps: {optim_step_time_cum}")
            print(f"Total time spent box constraining input: {box_constraint_time_cum}")
            print(f"Total time spent checking for IS and updating: {is_check_time_cum}")
            print(f"Total time spent restarting initializations: {restart_time_cum}")
        
        print(f"Initializations solved: {initializations_solved}")

        self.solution["graph_mask"] = MIS
        self.solution["size"] = best_MIS
        self.solution["number_of_steps"] = number_of_iterations_T
        self.solution["steps_to_best_MIS"] = steps_to_best_MIS
