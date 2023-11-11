import torch
import numpy
import networkx as nx
from lib.custom_layers import ElementwiseMultiply


def datalessNN_graph_params(
    graph, seed=10, numpy_dtype=numpy.float32, torch_dtype=torch.float32
):
    ## Normalize graph labels to 0 - {Number of nodes} (this will help with indexing our graph-related weights)
    G = nx.relabel.convert_node_labels_to_integers(graph)

    ## Set numpy seed. This is used for theta initialization
    numpy.random.seed(seed=seed)

    ## Graph order: number of nodes. Graph size: number of edges.
    graph_order = len((G.nodes))
    graph_size = len((G.edges))
    graph_complement_size = (graph_order * (graph_order - 1)) // 2 - graph_size

    ##################################################################################################
    ##################################################################################################
    ################### MODIFY WEIGHTS of NN_p BASED ON GRAPH
    ##################################################################################################
    ##################################################################################################

    ##############################
    ## Theta value initilization
    ##############################
    list_of_node_degrees = [None] * graph_order
    for i in range(0, graph_order):
        list_of_node_degrees[i] = G.degree[i]

    max_node_degree_in_graph = numpy.max(list_of_node_degrees)

    theta_vector = numpy.zeros(graph_order, dtype=numpy_dtype)

    for i in range(0, graph_order):
        ## To prevent exact repititive probability: add some very small epsilon
        theta_vector[i] = (
            1
            - (list_of_node_degrees[i] / max_node_degree_in_graph)
            + numpy.random.uniform(low=0.0, high=0.1)
        )

    ###############################################
    ## Second layer weight and bias initilization
    ###############################################

    #### This is the numpy array we need to update the weights of the second layer (N x (N+M+Mc))
    second_layer_weights = numpy.zeros(
        shape=(graph_order, graph_order + graph_size + graph_complement_size),
        dtype=numpy_dtype,
    )

    #### Initilize the portion of the weight matrix reserved for the nodes of G
    for i in range(graph_order):
        second_layer_weights[i, i] = 1.0  # this stays the same

    #### Initilize the portion of the weight matrix reserved for the edges of G
    for idx, pair in enumerate(G.edges):
        second_layer_weights[pair[0], graph_order + idx] = 1.0
        second_layer_weights[pair[1], graph_order + idx] = 1.0

    #### Initilize the portion of the weight matrix reserved for the edges of G'
    G_complement = nx.complement(G)
    for idx, pair in enumerate(G_complement.edges):
        second_layer_weights[pair[0], graph_order + graph_size + idx] = 1.0
        second_layer_weights[pair[1], graph_order + graph_size + idx] = 1.0
    del G_complement

    #### This is the numpy array we need to update the biases of the second layer (N+M+Mc)
    second_layer_biases = numpy.zeros(
        shape=(graph_order + graph_size + graph_complement_size), dtype=numpy_dtype
    )

    ## Initilize the portion of the bias vector reserved for the nodes of G
    second_layer_biases[0:graph_order] = -0.5

    ## Initilize the portion of the bias vector reserved for the edges of G and G'
    second_layer_biases[
        graph_order : graph_order + graph_size + graph_complement_size
    ] = -1.0

    ##############################################
    ## Third layer weight initilization
    ##############################################

    #### This is the numpy array we need to update the weights of the third layer (N+M+Mc)
    third_layer_weights = numpy.zeros(
        shape=(graph_order + graph_size + graph_complement_size), dtype=numpy_dtype
    )

    #### add here from graph:
    third_layer_weights[0:graph_order] = -1.0
    third_layer_weights[graph_order : graph_order + graph_size] = graph_order
    third_layer_weights[graph_order + graph_size :] = -1.0

    T_1 = torch.clamp(torch.tensor(theta_vector, dtype=torch_dtype), 0.1, 0.9)
    W_2 = torch.tensor(second_layer_weights, dtype=torch_dtype)
    B_2 = torch.tensor(second_layer_biases, dtype=torch_dtype)
    W_3 = torch.tensor(third_layer_weights, dtype=torch_dtype)

    return {
        "theta_tensor": T_1,
        "layer_2_weights": W_2,
        "layer_2_biases": B_2,
        "layer_3_weights": W_3,
    }


def datalessNN_module(theta_tensor, layer2_weights, layer2_biases, layer3_weights, torch_dtype=torch.float32):

    graph_order = len(theta_tensor)
    graph_nodes_and_all_possible_edges = len(layer2_biases)

    ##################################################################3################################################
    ################################3 initialize NN ##################################################################3
    ##################################################################3################################################

    NN = torch.nn.Sequential()

    ###############################
    ## Theta Layer initialization
    ###############################
    theta_layer = ElementwiseMultiply(in_features=graph_order, out_features=graph_order)

    # Temporarily disable gradient calc to set initial weights
    with torch.no_grad():
        theta_layer.weight.data = theta_tensor

    NN.append(theta_layer)

    ################################
    ## Second Layer initialization
    ################################
    layer2 = torch.nn.Linear(
        in_features=graph_order,
        out_features=graph_nodes_and_all_possible_edges,
        bias=True,
        dtype=torch_dtype
    )
    # add ReLu activation layer to layer 2
    layer2_activation = torch.nn.ReLU()

    # make layer non-trainable
    layer2.requires_grad_(False)

    # Initialize weights and biases
    layer2.weight.data = numpy.transpose(layer2_weights)
    layer2.bias.data = layer2_biases

    NN.append(layer2)
    NN.append(layer2_activation)

    ###############################
    ## Third Layer initialization
    ###############################
    layer3 = torch.nn.Linear(
        in_features=graph_nodes_and_all_possible_edges, out_features=1, bias=False
    )

    # make layer non-trainable
    layer3.requires_grad_(False)

    # Initialize weights
    layer3.weight.data = layer3_weights
    
    NN.append(layer3)

    return NN