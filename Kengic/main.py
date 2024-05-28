from kengic import *

n = 3 #ngrams default = 3
parents = 5 #parents default = 5
hops = 1
nlogP = n #n used in loss function
optimiser = 3 #which cost fucntion to use
max_iters = 150 #max iterations default = 150
out_folder = 'output_captions'  

def main():
    ngram_dfs, keywords, references= initialize()
    
    #graph generation bottom up
    graph,edges = create_graph(ngram_dfs[n],keywords , n, parents, hops)
    
    #graph generation top down
    graph = top_down_traversal(graph, keywords, ngram_dfs)
    
    #graph traversal 
    top_captions, top_costs, V, iterations = traverse(graph, max_iters, keywords, nlogP, optimiser, ngram_dfs)
    
    bleuScores = get_metrics(top_captions, eval(references[1]))
    
    for i in range(len(top_captions)):
        print('\n', 'Caption:', top_captions[i], 'Cost:', top_costs[i], "bleuScores: ", bleuScores[i])

def initialize():
    input = pd.read_csv('./input.csv') #CNN output will be here
    img_id = input['img_id'].values[0]
    ngram_dfs,references = load_data(img_id)
    keywords = eval(input['keywords'].values[0])
    return ngram_dfs,keywords,references

main()
    