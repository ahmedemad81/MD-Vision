import os
import argparse
import json
import copy
import pandas as pd
import numpy as np
import time
import multiprocessing
import collections
import shutil
import math
import logging
import nlp
import pickle
import re
from nltk.translate.bleu_score import sentence_bleu


pd.options.mode.chained_assignment = None  # default='warn'
start_end_tokens = ['<t>', '</t>']

def load_splits(data):
        
    def update_dic(dic, key, value):
        if(key not in dic.keys()):
            dic[key] = []
        dic[key] += [value]
        
        return dic

    splits = {}
    filepaths_dic = {}

    for img in data['images']:
        update_dic(splits, img['split'], img['imgid'])
        update_dic(filepaths_dic, img['filepath'], img['imgid'])
    
    fulltrain = splits['train'] + splits['restval']
    splits['fulltrain'] = fulltrain
    # print("SPLITS!", splits)
    return splits, filepaths_dic
    
    
def ngrams_from_dic_to_df(ngrams):
    ngrams_dfs = {}

    for ni in range(1, 6):
        columns = [i for i in range(1,ni+1)]
        # print(columns)
        ngrams_df = pd.DataFrame(ngrams[ni], columns=columns)
        # print(ngrams_df.head())
        ngrams_df['count'] = 0
        # print(ngrams_df.head())
        ngrams_df = ngrams_df.groupby(columns).count().sort_values(['count'], ascending=False).reset_index()
        # print(ngrams_df.head())
        ngrams_df['probability'] = ngrams_df['count']/ngrams_df['count'].sum()
        # print(ngrams_df.head())
        ngrams_dfs[ni] = ngrams_df

    return ngrams_dfs


def generate_stopwords_file(stopwords_file_path):
        from nltk.corpus import stopwords
        pd.DataFrame(stopwords.words('english'), columns=['stopword']).to_csv(stopwords_file_path, index=False)
        
        
def get_stopwords(stopwords_file_path):
    return list(pd.read_csv(stopwords_file_path)['stopword'].values)


def initialise_folder(folder_path):
    if not os.path.exists(folder_path):
        os.mkdir(folder_path)
    else:
        shutil.rmtree(folder_path)
        os.mkdir(folder_path)


class Optimiser():
    logP      = 1
    logP_H    = 2
    logP_HL   = 3
    logPN_HL  = 4
    logPND_HL = 5
    logP_L    = 6
    logPN_H   = 7
    logPN_L   = 8

    DESC = ['logP', 'logP_H', 'logP_HL', 'logPN_HL', 'logPND_HL', 'logP_L', 'logPN_H', 'logPN_L']
                                       

class KGCap():
    def __init__(self, configs, path_karpathy_coco_splits, stopwords_file_path, out_folder,
                input_csv_file_path, num_imgs, keywords_column, keywords_type='all', keywords_split=False,
                include_start_end_tokens=False, top_n_captions=5, num_processes=multiprocessing.cpu_count()):
        
        self.path_karpathy_coco_splits = path_karpathy_coco_splits
        self.stopwords_file_path = stopwords_file_path

        self.configs = configs
        self.out_folder = out_folder
        initialise_folder(self.out_folder)        
        
        self.log(os.getcwd())
        self.input_csv_file_path = input_csv_file_path
        self.num_imgs = num_imgs
        
        self.keywords_column = keywords_column
        self.keywords_type = keywords_type
        self.keywords_split = keywords_split
        self.include_start_end_tokens = include_start_end_tokens
        self.top_n_captions = top_n_captions

        self.num_processes = num_processes
        
        c = self.configs
        self.log('===========================================================================')
        self.log('Running KGCap (n: ' + str(c[0]) + ' parents: ' + str(c[1]) + ' hops: ' + str(c[2]) + ' nlogP: ' + str(c[3]) + ' optimiser: ' + str(c[4]) + ' max_iters: ' + str(c[5]) + ')')
        self.log('---------------------------------------------------------------------------')
        self.log('input_csv_file_path: ' + str(self.input_csv_file_path))
        self.log('num_of_images: ' + str(self.num_imgs))
        self.log('keywords_column: ' + str(self.keywords_column))
        self.log('keywords_type: ' + str(self.keywords_type))
        self.log('keywords_split: ' + str(self.keywords_split))
        
        self.log('include_start_end_tokens: ' + str(self.include_start_end_tokens))
        self.log('top_n_captions: ' + str(self.top_n_captions))

        self.log('out_folder: ' + str(self.out_folder))
        self.log('num_of_processes: ' + str(self.num_processes))
        self.log('===========================================================================')

        self.references= None
        
        data, ngrams_dfs, stopwords = self.load_data()
        
        
        
        self.data = data
        self.ngrams_dfs = ngrams_dfs
        self.stopwords = stopwords

    def read_karpathy_splits(self):
        with open(self.path_karpathy_coco_splits) as json_file:
            data = json.load(json_file)
        return data
    
    def readMedicalSet4(self):
        #read indiana dataset 
        df = pd.read_csv('./indiana_reports.csv')

        #to capture
        measurement = re.compile(r'(\d+(.\d+)?)( )?((cm|mm)?( )?(x) (\d+(.\d+)?) )?(cm|mm)')
        ratio = re.compile(r'(\d+(.\d+)\/)')
        rankNumbers = re.compile(r'[0-9](st|nd|rd|th)', re.I)
        words = re.compile(r'(day|film|recommend|prior|comparison|compare|image|T6|T8|T11|T12)', re.I)
        intact = re.compile(r'((?<= )( )?(is|are) intact)|((?<=  )(is|are) unremarkable)')
        #create a new dataframe df2
        df2 = pd.DataFrame()
        # df2['uid'] = df['uid']

        df['findings'] = df['findings'].str.replace(r'XXXX', '',regex = True)
        df['impression'] = df['impression'].str.replace(r'(XXXX\.|XXXX)', '',regex = True)

        #removing any 2.0 cm or 2.0 x 2.0 cm or 2.0 cm or 2.0mm or 2.0 x 2.0mm or 2.0mm x 2.0mm etc.
        # df['findings'] = df['findings'].str.replace(r'(\d+(.\d+)?)( )?((cm|mm)?( )?(x) (\d+(.\d+)?) )?(cm|mm)', '',regex=True)
        # df['impression'] = df['impression'].str.replace(r'(\d+(.\d+)?)( )?((cm|mm)?( )?(x) (\d+(.\d+)?) )?(cm|mm)', '',regex=True)

        #remove any list numbu2. 3. and so on
        df['findings'] = df['findings'].str.replace(r'([0-9](\.))|(^[0-9](\.))', '',regex=True)
        df['impression'] = df['impression'].str.replace(r'([0-9](\.))|(^[0-9](\.))', '',regex=True) 

        #remove comas
        df['findings'] = df['findings'].str.replace(r',|-', '',regex=True)
        df['impression'] = df['impression'].str.replace(r',|-', '',regex=True)

        #split each to plst of sentences 
        df['findings'] = df['findings'].map(lambda x: str(x).split('.'))
        df['impression'] = df['impression'].map(lambda x: str(x).split('.'))


        df['findings'] = df['findings'].apply(lambda x: [sentence for sentence in x if not (intact.search(sentence) or words.search(sentence) or rankNumbers.search(sentence) or measurement.search(sentence) or ratio.search(sentence))])
        df['impression'] = df['impression'].apply(lambda x: [sentence for sentence in x if not (intact.search(sentence) or words.search(sentence) or rankNumbers.search(sentence) or measurement.search(sentence) or ratio.search(sentence))])

        #loop on the each senctence in the list of sentences and remove any remaining numbers from the sentence 
        df['findings'] = df['findings'].apply(lambda x: [re.sub(r'\d+', '', sentence) for sentence in x])
        df['impression'] = df['impression'].apply(lambda x: [re.sub(r'\d+', '', sentence) for sentence in x])

        #remove any empty sentences
        df['findings'] = df['findings'].apply(lambda x: [sentence for sentence in x if sentence.strip()])
        df['impression'] = df['impression'].apply(lambda x: [sentence for sentence in x if sentence.strip()])

        df2['captions'] = df['findings'] + df['impression']
        
        
        df3 = df2.explode("captions")
        df3.explode("captions")
        #save df2 in csv 
        # split sentence and remove any row that has words that are <= 2
        df3 = df3['captions'].map(lambda x: str(x).split())
        # remove any row of size <= 2 
        df3 = df3[df3.map(len) > 2]
        
        data = pd.DataFrame(df3)
        return df3, data
    
    def readMedicalSet3(self):
        df = pd.read_parquet('./train-00000-of-00001-0dc3c7ebb0311aec.parquet')
        formatted_df = pd.DataFrame()
        #split the text given in to sentences
        #remove the following from findings and impression
        # any ___
        formatted_df['FINDINGS'] = df['FINDINGS'].str.replace(r'___', '', regex = True)
        formatted_df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'___', '', regex = True)

        # any Dr.
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'Dr.', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'Dr.', '', regex = True)

        # any time formats ex: at 12:00 / at floating numbers
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'(at \d{1,2}:\d{1,2})|(\d{1,2}:\d{1,2})', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'(at \d{1,2}:\d{1,2})|(\d{1,2}:\d{1,2})', '', regex = True)

        # any p.m/a.m/am/pm
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'( am )|( pm )|( p\.m)|( a\.m)', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'( am )|( pm )|( p\.m)|( a\.m)', '', regex = True)

        # remove floating numbers followed by measurements ex: 12.5
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'\d+\.\d+', '', regex = True)
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'\d+\.', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'\d+\.\d+', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'\d+\.', '', regex = True)

        #remove any cm mm inch
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'( cm)|( mm)', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'( cm)|( mm)', '', regex = True)

        # remove any 1.,2.,3.,etc.
        #done in the above step

        # remove , =
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r',|=', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r',|=', '', regex = True)

        #remove any numbers
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'\d+', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'\d+', '', regex = True)

        #remove any \n
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].str.replace(r'\n', '', regex = True)
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].str.replace(r'\n', '', regex = True)

        #split each paragraph on .
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].map(lambda x: str(x).split('.'))
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].map(lambda x: str(x).split('.'))

        #remove empty strings
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].map(lambda x: [i.split() for i in x if i != ''])
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].map(lambda x: [i.split() for i in x if i != ''])

        #check for since, through, by, on,
        #make every token a lower case 
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].apply(lambda x: [[word.lower() for word in sentence] for sentence in x])
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].apply(lambda x: [[word.lower() for word in sentence] for sentence in x])


        # #remove at ; however, new, from the sentence 
        toRemove = ['at', 'however', 'new', 'from',';']
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].apply(lambda x: [[word for word in sentence if word not in toRemove] for sentence in x])
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].apply(lambda x: [[word for word in sentence if word not in toRemove] for sentence in x])


        #remove sentence with through, since, submitted, unchanged, compared, comparison, previous, prior,increase, decrease,increased, decreased,
        #findings, film, PICC, yesterday, today, SVC, tube,  
        toRemoveSentence = ['through', 'since', 'submitted', 'unchanged', 'compared', 'comparison', 'previous', 'prior', 'increase', 'decrease', 'increased', 'decreased', 'findings', 'film', 'picc', 'yesterday', 'today', 'svc', 'tube']
        formatted_df['FINDINGS'] = formatted_df['FINDINGS'].apply(lambda x: [sentence for sentence in x if not any(word in sentence for word in toRemoveSentence)])
        formatted_df['IMPRESSION'] = formatted_df['IMPRESSION'].apply(lambda x: [sentence for sentence in x if not any(word in sentence for word in toRemoveSentence)])

        finalDf = pd.DataFrame()
        finalDf['captions'] = formatted_df['FINDINGS'] + formatted_df['IMPRESSION']

        # remove ['as','above'],['status','quo']
        toRemoveSentence = ['above', 'quo']
        finalDf['captions'] = finalDf['captions'].apply(lambda x: [sentence for sentence in x if (not any(word in sentence for word in toRemoveSentence) and len(sentence) > 2)])
        
        return finalDf
    
    def readMedicalSet2(self): 
        df = pd.read_parquet('./train-00000-of-00001-0dc3c7ebb0311aec.parquet')
         
        #remove "___" from the text
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'___', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'___', '')
        
        #remove any . and , in the text in findings and impression
        df['FINDINGS'] = df['FINDINGS'].str.replace('.', '')
        df['FINDINGS'] = df['FINDINGS'].str.replace(',', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace('.', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(',', '')

        #remove any time formats from the text in findings and impression
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'\d{1,2}:\d{1,2}', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'\d{1,2}:\d{1,2}', '')

        #remove any am and pm
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'am', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'am', '')
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'pm', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'pm', '')

        #remove any numbers 
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'\d+', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'\d+', '')

        #remove any dr titles
        df['FINDINGS'] = df['FINDINGS'].str.replace(r'dr.|Dr.', '')
        df['IMPRESSION'] = df['IMPRESSION'].str.replace(r'dr.|Dr.', '')

        df2 = pd.DataFrame()
        df.head()
        df2['captions'] = df['FINDINGS'].map(lambda x: [{'sentence': x, 'tokens': str(x).split()}])
        df2['captions'] += df['IMPRESSION'].map(lambda x: [{'sentence': x, 'tokens': str(x).split()}])
        
        return df2
    
    def readMedicalSet(self): # ADDED new function to read the medical dataset
        
        #read indiana dataset 
        df = pd.read_csv('./indiana_reports.csv')
        
        #create a new dataframe df2
        df2 = pd.DataFrame()
        df2['uid'] = df['uid']
        
        df['findings'] = df['findings'].str.replace(r'XXXX', '')
        df['impression'] = df['impression'].str.replace(r'x-XXXX.', '')
        df['impression'] = df['impression'].str.replace(r'XXXX.', '')
        
        #remove any . and , in the text in findings and impression
        df['findings'] = df['findings'].str.replace('.', '')
        df['findings'] = df['findings'].str.replace(',', '')
        df['impression'] = df['impression'].str.replace('.', '')
        df['impression'] = df['impression'].str.replace(',', '')
        
        #remove any numbers in the text in findings and impression
        df['findings'] = df['findings'].str.replace('\d+', '')
        df['impression'] = df['impression'].str.replace('\d+', '')
        
        #take the findings and impression and create a new column called captions excluding nan rows
        # df = df.dropna(subset=['findings', 'impression'])
        # Now create the 'captions' column
        df2['captions'] = df['findings'].map(lambda x: [{'sentence': x, 'tokens': str(x).split()}])
        df2['captions'] += df['impression'].map(lambda x: [{'sentence': x, 'tokens': str(x).split()}])

        # df2 = df2.dropna(subset=['captions'])

        return df2  
          
          
    def load_ngrams(self, data):
        # graph = {}
        # weights = {}

        # all_tokens = []
        # total_images = 0
        current_images = 0

        ngrams_dic = {}
        ngrams1 = []
        ngrams2 = []
        ngrams3 = []
        ngrams4 = []
        ngrams5 = []
        ngrams6 = []
        ngrams7 = []
        ngrams8 = []
        ngrams9 = []

        

        # if len(img_ids) == 0:
        #     list_of_images = splits['fulltrain'][0:num_of_images]
        #     total_images = num_of_images
        # else:
        #     list_of_images = splits['fulltrain']
        #     total_images = len(img_ids)
            
        # get number dataframe rows
        total_captions = data.shape[0]
        
        for index, row in data.iterrows():
            
            if (index+1)%10000 == 0:
                self.log(str(index+1) + ' of ' + str(total_captions))
            
            # for s in row['captions']:
                # sentence = s['sentence']
                # #is value is nan
                # if pd.isnull(sentence):
                #     continue
                
            tokens = row['captions']
            n1 = nlp.ngrams(['<t>'] + tokens + ['</t>'], 1)
            ngrams1 += n1
            
            n2 = nlp.ngrams(['<t>'] + tokens + ['</t>'], 2)
            
            ngrams2 += n2
            #print(n2)

            ngrams3 += nlp.ngrams(['<t>', '<t>'] + tokens + ['</t>'], 3)
            ngrams4 += nlp.ngrams(['<t>', '<t>', '<t>'] + tokens + ['</t>'], 4)
            ngrams5 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 5)
            ngrams6 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 6)
            ngrams7 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 7)
            ngrams8 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 8)
            ngrams9 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>', '<t>','<t>'] + tokens + ['</t>'], 9)
            
            #             self.log(str(current_images+1) + ' of ' + str(total_images))
            # if current_images < total_images:
            #     if len(img_ids) != 0 and imgid not in img_ids:
            #         pass
            #     else:
            #         #print('imgid: ' + str(imgid))
            #         if (current_images+1)%10000 == 0:
            #             self.log(str(current_images+1) + ' of ' + str(total_images))
                    
            #         for s in data['images'][imgid]['sentences']:
            #             tokens = s['tokens']
                        
            #             n1 = nlp.ngrams(['<t>'] + tokens + ['</t>'], 1)
            #             ngrams1 += n1
                        
            #             n2 = nlp.ngrams(['<t>'] + tokens + ['</t>'], 2)
                        
            #             ngrams2 += n2
            #             #print(n2)

            #             ngrams3 += nlp.ngrams(['<t>', '<t>'] + tokens + ['</t>'], 3)
            #             ngrams4 += nlp.ngrams(['<t>', '<t>', '<t>'] + tokens + ['</t>'], 4)
            #             ngrams5 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 5)
            #             ngrams6 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 6)
            #             ngrams7 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 7)
            #             ngrams8 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>', '<t>'] + tokens + ['</t>'], 8)
            #             ngrams9 += nlp.ngrams(['<t>', '<t>', '<t>', '<t>', '<t>', '<t>', '<t>','<t>'] + tokens + ['</t>'], 9)


            #             all_tokens += tokens

            #         current_images += 1
            # else:
            #     break
        
        ngrams_dic[1] = ngrams1
        ngrams_dic[2] = ngrams2
        ngrams_dic[3] = ngrams3
        ngrams_dic[4] = ngrams4
        ngrams_dic[5] = ngrams5
        ngrams_dic[6] = ngrams6
        ngrams_dic[7] = ngrams7
        ngrams_dic[8] = ngrams8
        ngrams_dic[9] = ngrams9

        return ngrams_dic


    def load_data(self):
        self.log('------------------------------------------------')
        # self.log('Reading karpathy splits...')
        # data = self.read_karpathy_splits()
        
        
        # self.log(type(data))
        #print first data
        # print(data['images'][0])
        #data = {'dataset': 'coco' , 'images': }
        #data['images'][0] = {'cocoid': , 'filename': , 'filepath': , 'imgid': , 'sentences': [{'tokens': , 'raw': , 'imgid': , 'sentid': }], 'split': }
        self.log('Reading Medical dataset...')
        data2, data = self.readMedicalSet4()
        
        newList = data2.values.tolist()
        
        # Convert each inner list to a tuple and add them to a set
        unique_reference = set(tuple(x) for x in newList)

        # Convert each tuple in the set back to a list
        unique_reference = [list(x) for x in unique_reference]
        
        self.references = unique_reference
        
        # self.log('------------------------------------------------')
        # self.log('Loading splits...')
        # splits, _ = load_splits(data) #bte2sem el data bta3t el images w el sentensec le kaza splits
        # #dictionary of splits train, test, ....

        self.log('------------------------------------------------')
        self.log('Loading n-grams...')
        
        ngrams_dic = {}
        try:
            self.log('Loading ngrams_dic.pkl...')
            with open('ngrams_dic.pkl','rb') as f:
                ngrams_dic = pickle.load(f)
        except:
            self.log('Failed to Load ngrams_dic.pkl...')

            ngrams_dic= self.load_ngrams(data) #bet return kol el tokens w ngrams_dic
            #save ngrams_dic bta3 kaza no3 ngram mn 1-9
        
            self.log('saving ngrams_dic.pkl...')
            with open('ngrams_dic.pkl', 'wb') as f:
                pickle.dump(ngrams_dic, f)  

        
        self.log('------------------------------------------------')
        self.log('Loading n-grams into DataFrames...')
        ngrams_dfs = ngrams_from_dic_to_df(ngrams_dic) #dict feha kol dataframe le kaza ngram
        #y3ny ngrams_dfs[1] = dataframe le ngram 1, ngrams_dfs[2] = dataframe le ngram 2, ...
        
        

        self.log('------------------------------------------------')
        self.log('Loading stopwords...')
        stopwords = get_stopwords(self.stopwords_file_path) #;ist of stopwords
        
        return data, ngrams_dfs, stopwords


    def get_imgids_with_phrase(self, phrase, log=False):
        phrase = ' ' + phrase + ' '
        img_ids = []
        idx = 0
        for img in self.data['images']:
            for s in img['sentences']:
                caption = ' '.join(s['tokens'])
                if phrase in caption:
                    imgid = img['imgid']
                    img_ids += [imgid]
                    if log:
                        print(idx, 'imgid: ', imgid, ' - [', phrase, '] is in: ', caption)
                    idx += 1
                    break
    
        return img_ids

    ####################################################################################################################
            
    def go_from(self, n, from_node, spread):
        '''
        This function is used to go from a node to a set of n-grams.
        The set of this size depends on the spread
        
        Args:
            n-grams_dfs: pandas DataFrame of n-grams
            n: size of n-gram
            from_node: starting node
            spread: number of n-grams to consider

        Returns:
            pd.DataFrame: n-grams        

        '''
        ngrams_df = self.ngrams_dfs[n]


        from_node = from_node.split()[0]
        ngrams_from = ngrams_df[ngrams_df[n] == from_node] # hatly kol el n-grams 
                        # ely kelmet from node feha fe 25r el n-gram

        #if len(from_node_split) == 1:
        #ngrams_from = ngrams_df[ngrams_df[n] == from_node_split[0]] # UPDATE v2

        # else:
        #     ngrams_from = ngrams_df
        #     for i in range(len(from_node_split)):
        #         ngrams_from = ngrams_from[ngrams_from[n-i] == from_node_split[::-1][i]]


        #ngrams_from = ngrams_df[ngrams_df[n].isin(get_similar_nodes(from_node, ngrams_dfs, n))]
        #print(ngrams_from)
        
        # by7seb en el history geh abl el klma de kam mara w y7ot el probability
        # beye7seb en this parent came before this keyword, 3shan el keyword heya elly sabta hena
        ngrams_from['from_prob'] = ngrams_from['count']/float(ngrams_from['count'].sum())
        
        if spread == ':': #eh el far2???????? #==> Spread is the number of parents to return
            ngrams_from = ngrams_from.sort_values(['from_prob'], ascending=False)
        else:
            ngrams_from = ngrams_from.sort_values(['from_prob'], ascending=False)[0:spread]

        

        return ngrams_from

    def go_to(self, words):
        '''
        This function is used to go to a node to a set of n-grams.    
        
        Args:
            n-grams_dfs: pandas DataFrame of n-grams
            n: size of n-gram
            from_node: starting node

        Returns:
            pd.DataFrame: n-grams        

        '''

        n = len(words)
        ngrams = self.ngrams_dfs[n]
        prev_ngrams = None
        for i, f in enumerate(words):        
            ngrams = ngrams[ngrams[i+1] == f]
            
            if i+1 == len(words) - 1:
                prev_ngrams = ngrams
        
        if prev_ngrams is not None:
            ngrams['count_prev'] = prev_ngrams['count'].sum()
            ngrams['conditional_prob'] = ngrams['count']/prev_ngrams['count'].sum()
        
        return ngrams

    def remove_stopwords(self, words):
        filtered_words = []
        for w in words:
            if w not in self.stopwords:
                filtered_words += [w]

        return filtered_words


    def get_graph(self, keywords, n, neighbourhood, hops, split=False, pid=0):

        if split: # handling multi-word keywords w dh 7aso malosh lazma because we handled 
                    # it in the previous steps
            keywords_ = []
            for k in keywords:
                keywords_ += k.split()
            keywords = keywords_

        self.log('pid:' + str(pid) + ' - Generating graph for keywords:' + str(keywords) + ' (n:' + str(n) + ' neighbourhood:' + str(neighbourhood) + ' hops:' + str(hops) + ')')
        queue = keywords
        hop = 0

        columns = [i for i in range(1, n+1)]
        graph = {}
        edges = {}

        previous_neighbourhood = neighbourhood #ely howa kam p (number of parents)

        from_del = '{'
        to_del = '}'
        
        global_min_conns_count = np.inf
        
        while hop < hops and len(queue) > 0: #nafs el agorithim
            from_ngram_sp = queue[0].split()
            
            if len(from_ngram_sp) == 1:
                from_ngram = from_ngram_sp[0]
            else:
                from_ngram = ' '.join(from_ngram_sp[0:-1])
            
            from_node = queue[0]
            queue = queue[1:]

            if from_del in from_node:
                idx_from = from_node.index(from_del)
                idx_to = from_node.index(to_del)
                current_hop = int(from_node[idx_from+1:idx_to])

                if current_hop > hop:
                    hop = hop + 1

            elif from_node not in self.stopwords:
                current_neighbourhood = neighbourhood #round(neighbourhood/math.exp(hop))

                if current_neighbourhood != previous_neighbourhood:
                    self.log('pid:' + str(pid) + ' - setting neighbourhood to: ' + str(current_neighbourhood) + ' for hop:' + str(hop))
                    previous_neighbourhood = current_neighbourhood

                #fe el algorithim de [getP()]
                from_ngrams = self.go_from(n, from_node, current_neighbourhood) #gab 23la 5 probabilities were en el kelma fe 25r el ngram   
                conns = from_ngrams[columns].apply(lambda x: ' '.join(x), axis=1).values
                
                # setting min connections count in graph
                counts = list(from_ngrams['count'].values)
                if len(counts) > 0:
                    min_conns_count = min(counts)

                    if min_conns_count < global_min_conns_count:
                        global_min_conns_count = min_conns_count
                    
                if from_ngram not in graph.keys():
                    graph[from_ngram] = []

                for ci, c in enumerate(conns):
                    parent_node = ' '.join(c.split()[0:-1])
                    from_prob = from_ngrams[ci:ci+1]['from_prob'].values[0]
                    edges[parent_node + ':' + from_ngram] = from_prob

                    graph[parent_node] = [from_ngram]

                queue += [from_del + str(hop+1) + to_del] + list(conns)
        
        return graph, edges, global_min_conns_count


    def is_in(_, word, keys):
        for k in keys:
            if word in k:
                return k
        return None


    def get_similar_nodes(self, node, n):
        similar_nodes = []
        for n in self.ngrams_dfs[n][n].unique():
            if node in n:
                similar_nodes += [n]
        return similar_nodes


    def check_connection(self, phrase):
        phrase = phrase.replace('<t>', '').replace('</t>', '')
        ngrams_dfs = self.ngrams_dfs
        ps = phrase.split()
        n = len(ps)

        ngrams = []

        if n == 1:
            ngrams = ngrams_dfs[1][ngrams_dfs[1][1] == ps[0]]
        elif n == 2:
            ngrams = ngrams_dfs[2]
            ngrams = ngrams[ngrams[1] == ps[0]]
            ngrams = ngrams[ngrams[2] == ps[1]]
        elif n == 3:
            ngrams = ngrams_dfs[3]
            ngrams = ngrams[ngrams[1] == ps[0]]
            ngrams = ngrams[ngrams[2] == ps[1]]
            ngrams = ngrams[ngrams[3] == ps[2]]
        elif n == 4:
            ngrams = ngrams_dfs[4]
            ngrams = ngrams[ngrams[1] == ps[0]]
            ngrams = ngrams[ngrams[2] == ps[1]]
            ngrams = ngrams[ngrams[3] == ps[2]]
            ngrams = ngrams[ngrams[4] == ps[3]]
        elif n == 5:
            ngrams = ngrams_dfs[5]
            ngrams = ngrams[ngrams[1] == ps[0]]
            ngrams = ngrams[ngrams[2] == ps[1]]
            ngrams = ngrams[ngrams[3] == ps[2]]
            ngrams = ngrams[ngrams[4] == ps[3]]
            ngrams = ngrams[ngrams[5] == ps[4]]

        else:
            count = len(self.get_imgids_with_phrase(phrase))
        
        if len(ngrams) > 0:
            count = ngrams['count'].values[0]
        else:
            count = 0

        return count


    def post_process_graph(self, graph, keywords, pid=0, min_conns=1): #top down connections construction
        self.log('pid:' + str(pid) + ' - Post-processing graph (size:' + str(len(graph.keys())) + ') keywords:' + str(keywords) + ' min conns:' + str(min_conns))

        for ni in graph.keys(): #keywords [ski, on a, mountain]
            for n in graph.keys(): #nafs el fekra [ski, on a, mountain]
                n_split = n.split()
    
                if ni != n and n_split[0] != '<t>':
                    phrase = ni + ' ' + n
                    conns = self.check_connection(phrase) 

                    if conns >= min_conns:
                        if n not in graph[ni]:
                            graph[ni] += [n]
        
        return graph


    def visualise_graph(_, graph, detected_nodes=[]):
        from pyvis.network import Network
        
        net = Network(directed=True, width="100%", height="100%")
        node_colour_default = '#ffffff'
        node_colour_start = '#93c47d'
        node_colour_detected = '#ffbf00'
        node_colour_end = '#e91818'
        
        # creating nodes
        for token in graph.keys():
            detected = False
        
            for ti in token.split():
                if ti in ' ' .join(detected_nodes).split():
                    node_colour = node_colour_detected
                    detected = True
                    break

            if not detected:
                node_colour = node_colour_default
                
            net.add_node(token, label=token, color=node_colour)
            node_colour = node_colour_default
            
        # adding connections
        for token in graph.keys():
            for con in graph[token]:
                net.add_edge(token,con)
                    
        options = """
                    var options = {
                    "physics": {
                        "repulsion": {
                        "springLength": 310
                        },
                        "minVelocity": 0.75,
                        "solver": "repulsion"
                    },
                    "interaction": {
                        "multiselect": true
                    }
                    }
                """

               
        #net.show_buttons(filter_=['physics', 'nodes'])
        net.set_options(options)
        net.show('graph.html')


    def remove_edge_to(_, graph, node):
        g_temp = copy.deepcopy(graph)
        for n in g_temp.keys():
            if node in g_temp[n]:
                g_temp[n] = g_temp[n].remove(node)
                if g_temp[n] is None:
                    g_temp[n] = []

        return g_temp


    def initialise_paths(_, paths, keywords):
        for k in keywords:
            paths += [[k]]

        return paths


    def remove_path(_, paths, path):
        filtered_paths = []
        for p in paths:
            if p != path:
                filtered_paths += [p]
        return filtered_paths


    def keywords_in_path(_, path, keywords):
        found = 0
        for k in keywords:
            if k in path:
                found += 1
        return found


    def set_global_paths(_, global_paths, global_log_probs, top_log_probs, top_paths, top_n):
        if global_paths == []:
            global_paths = top_paths
            global_log_probs = top_log_probs

        else:
            for i, p in enumerate(top_paths):
                if p not in global_paths:
                    global_paths += [p]
                    global_log_probs += [top_log_probs[i]]

            # global_paths += top_paths
            # global_log_probs += top_log_probs

            global_log_probs_ = np.array(global_log_probs)
            global_paths_ = np.array(global_paths, dtype=list)

            max_idx = np.argsort(global_log_probs_*-1)
            global_log_probs = global_log_probs_[max_idx].tolist()[0:top_n]
            global_paths = global_paths_[max_idx].tolist()[0:top_n]

        return global_paths, global_log_probs


    def find_num_of_children_in_path(_, path, children):
        found = 0

        for ci in children:
            if ci in path:
                found += 1

        return found


    def all_start_tokens(_,ngrams):
        for ng in ngrams:
            if ng != '<t>':
                return False
        
        return True

    def get_log_prob(self, caption_tokens, n):
        total_log_prob = 0

        if len(caption_tokens) < n:
            pad_size = n - len(caption_tokens)
            caption_tokens = ['<t>']*pad_size + caption_tokens
            
        for idx, _ in enumerate(caption_tokens[0:len(caption_tokens)-n+1]):
            gram = caption_tokens[idx:idx+n]
            log_prob = np.log(self.go_to(gram)['conditional_prob']).values #bygen el conditional probalility
                                    # bta3t el gram w y3mlaha LOG 
            
            if len(log_prob) > 0:
                total_log_prob += log_prob[0]
            
            elif self.all_start_tokens(gram):
                total_log_prob += 1
            else:
                total_log_prob += -1*np.inf
                
        return total_log_prob

    def get_extra_nouns(_, caption_tokens, keywords):
        return list(set(nlp.filter_pos(caption_tokens, 'n')).difference(set(keywords)).difference(set(start_end_tokens)))

    def get_duplicates(_, caption_tokens):
        hist = pd.DataFrame(caption_tokens, columns=['word'])['word'].value_counts().reset_index(name='count')
        #print head of hist
        # print(hist.head())
        return list(set(hist[hist['count'] > 1].index).difference(set(start_end_tokens)))
            
    def ngrams_log_prob(self, caption_tokens, n, keywords=[], optimiser=1):
        keywords = ' '.join(keywords).split() # handling multi-word keywords
        total_log_prob = self.get_log_prob(caption_tokens, n) #byrag3 el total conditional probability
                        #bta3t el caption_tokens
        
        if optimiser > 1:
            length = 0
            extra_nouns = self.get_extra_nouns(caption_tokens, keywords) # hena bysta5dm el POS 
            #tagging w ygeb el nouns ely fe el caption w y7othom fe list w diffence m3 el keywords w trga3 fe list extra_nouns

            if keywords == []:
                hits = 1
            else:
                hits = len(set(caption_tokens).intersection(set(keywords)))
                
                if hits == 0:
                    hits = 1e-3

            length = len(caption_tokens)

            if optimiser == Optimiser.logP_H:
                total_log_prob /= float(hits)

            elif optimiser == Optimiser.logP_L:
                 total_log_prob = total_log_prob/float(length)

            elif optimiser == Optimiser.logP_HL:
                total_log_prob = total_log_prob/float((hits)*length)

            elif optimiser == Optimiser.logPN_H:
                total_log_prob = (total_log_prob*(len(extra_nouns)+1))/float(hits)

            elif optimiser == Optimiser.logPN_L:
                total_log_prob = (total_log_prob*(len(extra_nouns)+1))/float(length)

            elif optimiser == Optimiser.logPN_HL:
                total_log_prob = (total_log_prob*(len(extra_nouns)+1))/(float((hits)*length))
            
            elif optimiser == Optimiser.logPND_HL:
                if total_log_prob != np.inf*-1:
                    duplicates = self.get_duplicates(caption_tokens)
                    total_log_prob = (total_log_prob*(len(extra_nouns)+1)*len(duplicates)+1)/(float((hits)*length))
            
            if length == 0:
                    total_log_prob = -1*np.inf

        return total_log_prob

    def maximise_log_prob(self, phrases, x, n, keywords, optimiser):
        if len(phrases) < x:
            x = len(phrases)

        top_captions = [''] * x
        highest_log_probs = np.ones(x)*(-1*np.inf)
        min_inf = 0

        for _, c in enumerate(phrases):#[[asasdad,asdasda,asdad],[asdadad,asdadad,asdadad],[asdadad asdadad asdadad]]
            padded_c = c 

            if len(c) < n:
                padded_c = ['<t>']*(n-len(c)) + c

            c_ = ' '.join(padded_c).split()
            
            log_prob = self.ngrams_log_prob(c_, n, keywords, optimiser) # bygeb el Conditional probability
                #bta3t el caption w ystad5mha 3lashan el cost function w byrag3 el cost function

            if log_prob == np.inf*-1:
                min_inf += 1

            min_highest_index = np.argmin(highest_log_probs)

            if log_prob > highest_log_probs[min_highest_index]:
                highest_log_probs[min_highest_index] = log_prob
                top_captions[min_highest_index] = c

        order = np.argsort(highest_log_probs*-1)
        top_captions = np.array(top_captions, dtype=list)[order].tolist()
        highest_log_probs = highest_log_probs[order].tolist()

        if '' in top_captions:
            empty_caps_idx = [i for i, j in enumerate(top_captions) if j != '']
            top_captions = np.array(top_captions, dtype=list)[empty_caps_idx].tolist()
            highest_log_probs = np.array(highest_log_probs, dtype=list)[empty_caps_idx].tolist()

        return top_captions, highest_log_probs


    def rank_captions(self, keywords, captions, global_paths, top_n, ngram, optimiser, pid=0):
            split_captions = []

            if len(captions) == 0:
                self.log('pid:' + str(pid) + ' - Setting global paths as captions...')
                split_captions = global_paths
            else:
                self.log('pid:' + str(pid) + ' - Computing log prob for captions...')
                for c in captions:
                    split_captions += [c.split()]

            captions, log_probs = self.maximise_log_prob(split_captions, top_n, ngram, keywords, optimiser)

            captions_ = []

            for c in captions:
                captions_ += [' '.join(c)]

            return captions_, log_probs
 

    def traverse(self, g, max_iters, keywords, nlogP, optimiser, pid=0):  
        start_from = list(keywords)
        if self.include_start_end_tokens:
            for k in g.keys():
                if 't>' in k:
                    start_from += [k]

        captions = []
        paths = []

        global_paths = []
        global_log_probs = []

        iterations = 0
        top_n = 5

        self.log('pid:' + str(pid) + ' - Traversing graph with nlogP:' + str(nlogP) + ' max iterations:' + str(max_iters) + ' top_phrases:' + str(top_n) + ' keywords:' + str(keywords))
        paths = self.initialise_paths(paths, start_from)
        # print('initialised paths:', paths)  
        
        # el path hema hya el Q bta3t el algorithim iterations hya qi max_iters hya qn
        while len(paths) > 0 and iterations < max_iters: 
            self.log('pid:' + str(pid) + ' ' + str(iterations) + '/' + str(max_iters) + ' ' + str(keywords) + ' paths:' + str(len(paths)) + ' captions:' + str(len(captions)))
            top_paths, top_log_probs = self.maximise_log_prob(paths, top_n, nlogP, keywords, optimiser)

            # setting top global paths and probabilities
            global_paths, global_log_probs = self.set_global_paths(global_paths, global_log_probs, top_log_probs, top_paths, top_n)

            if len(top_paths) > 0:
                paths = top_paths
            else:
                break

            p = paths[0]
            last_token = p[-1]
            children = g[last_token]

            found = self.find_num_of_children_in_path(p, children) #in paper  (C ∩ q)

            # no more nodes to traverse since all nodes have been visited
            
            # nafs el paper bs howa 3aksha
            # if |(C ∩ q)| == |C|
            if found == len(children):
                paths = self.remove_path(paths, p)

            else:
                for ci in children:
                    if ci not in p : #ci => c , p => q, keyword => K
                        if self.keywords_in_path(p, keywords) < len(keywords):
                            paths += [p + [ci]] #Concatenating child c with current path q
                        else: # if all keywords are in the q = |K|
                            caption = ' '.join(p)  # add path q to captions

                            if caption not in captions:
                                captions += [caption]

                        paths = self.remove_path(paths, p) #Remove current path q from set Q

            iterations += 1 #increment iterations
        
        self.log('pid:' + str(pid) + ' ' + str(iterations) + '/' + str(max_iters) + ' ' + str(keywords) + ' paths:' + str(len(paths)) + ' captions:' + str(len(captions)))
        captions, log_probs = self.rank_captions(keywords, captions, global_paths, top_n, nlogP, optimiser, pid)

        return captions, log_probs, len(g.keys()), iterations


    def hits(_, detected_tokens, caption):
        n = 0
        for dt in detected_tokens:
            if dt in caption:
                n += 1
        return n


    def get_captions_metrics(self, keywords, captions, probs, num_graph_nodes, iterations, pid=0):
        self.log('pid:' + str(pid) + ' - Generating captions metrics DataFrame...')
        configs = self.configs

        captions_df = pd.DataFrame(captions, columns=['caption'])
        # self.log('pid:' + str(pid) + ' - 1 Generating captions metrics DataFrame...')
        captions_df['caption_cleaned'] = captions_df['caption'].apply(lambda x: x.replace('<t>', '').strip())
        # self.log('pid:' + str(pid) + ' - 2 Generating captions metrics DataFrame...')
        captions_df['keywords'] = ', '.join(keywords)
        # self.log('pid:' + str(pid) + ' - 3 Generating captions metrics DataFrame...')
        captions_df['n'] = configs[0]
        # self.log('pid:' + str(pid) + ' - 4 Generating captions metrics DataFrame...')
        captions_df['parents'] = configs[1]
        # self.log('pid:' + str(pid) + ' - 5 Generating captions metrics DataFrame...')
        captions_df['hops'] = configs[2]
        #getting bleu score for each cap tion
        captions_df['bleu'] = captions_df['caption'].apply(lambda x: self.get_bleu_score(x, self.references))
        # self.log('pid:' + str(pid) + ' - 6 Generating captions metrics DataFrame...')
        captions_df['nlogP'] = configs[3]
        # self.log('pid:' + str(pid) + ' - 7 Generating captions metrics DataFrame...')
        captions_df['optimiser'] = configs[4]
        # self.log('pid:' + str(pid) + ' - 8 Generating captions metrics DataFrame...')
        captions_df['optimiser_desc'] = Optimiser.DESC[configs[4]-1]
        # self.log('pid:' + str(pid) + ' - 9 Generating captions metrics DataFrame...')
        captions_df['max_iters'] = configs[5]
        # self.log('pid:' + str(pid) + ' - 10 Generating captions metrics DataFrame...')
        captions_df['num_graph_nodes'] = num_graph_nodes
        # self.log('pid:' + str(pid) + ' - 11 Generating captions metrics DataFrame...')
        captions_df['iterations'] = iterations
        # self.log('pid:' + str(pid) + ' - 12 Generating captions metrics DataFrame...')
        captions_df['top_n_captions'] = self.top_n_captions
        # self.log('pid:' + str(pid) + ' - 13 Generating captions metrics DataFrame...')
        captions_df['keywords_type'] = self.keywords_type
        # self.log('pid:' + str(pid) + ' - 14 Generating captions metrics DataFrame...')
        captions_df['keywords_split'] = self.keywords_split
        # self.log('pid:' + str(pid) + ' - 15 Generating captions metrics DataFrame...')
        captions_df['start_end_tokens'] = self.include_start_end_tokens
        # self.log('pid:' + str(pid) + ' - 16 Generating captions metrics DataFrame...')

        captions_df['keywords_len'] = len(keywords)
        # self.log('pid:' + str(pid) + ' - 27 Generating captions metrics DataFrame...')
        captions_df['hits'] = captions_df['caption'].apply(lambda x : self.hits(keywords, x))
        # self.log('pid:' + str(pid) + ' - 26 Generating captions metrics DataFrame...')
        captions_df['length'] = captions_df['caption'].apply(lambda x : len(x.split()))
        # self.log('pid:' + str(pid) + ' - 25 Generating captions metrics DataFrame...')
        captions_df['hits/keywords'] = round(captions_df['hits']/captions_df['keywords_len'], 5)
        # self.log('pid:' + str(pid) + ' - 24 Generating captions metrics DataFrame...')
        captions_df['hits/length'] = round(captions_df['hits']/captions_df['length'], 5)

        # self.log('pid:' + str(pid) + ' - 23 Generating captions metrics DataFrame...')
        captions_df['extra_nouns'] = captions_df['caption'].apply(lambda x: self.get_extra_nouns(x.split(),keywords))
        # self.log('pid:' + str(pid) + ' - 22 Generating captions metrics DataFrame...')
        captions_df['extra_nouns_len'] = captions_df['extra_nouns'].apply(lambda x: len(x))

        # self.log('pid:' + str(pid) + ' - 21 Generating captions metrics DataFrame...')
        captions_df['duplicates'] = captions_df['caption'].apply(lambda x: self.get_duplicates(x.split()))
        # self.log('pid:' + str(pid) + ' - 20 Generating captions metrics DataFrame...')
        captions_df['duplicates_len'] = captions_df['duplicates'].apply(lambda x: len(x))

        # self.log('pid:' + str(pid) + ' - 19 Generating captions metrics DataFrame...')
        captions_df['log_prob'] = captions_df['caption'].apply(lambda x: self.get_log_prob(x.split(), configs[0]))
        # self.log('pid:' + str(pid) + ' - 18 Generating captions metrics DataFrame...')
        captions_df['log_prob_optimiser'] = probs
    
        
        # get bleu score for each caption
        
        
        # self.log('pid:' + str(pid) + ' - 17 Generating captions metrics DataFrame...')

        return captions_df

    def get_bleu_score(self, caption, references):
        candidate = caption.split()
        score = sentence_bleu(references, candidate)
        return score

    def get_captions_df(self, keywords, pid=0):
    
        try:
            conf = self.configs

            n = conf[0]
            parents = conf[1]
            hops = conf[2]
            nlogP = conf[3]
            optimiser = conf[4]
            max_iters = conf[5]

            t1 = time.time()

            if self.keywords_split:
                self.log('pid:' + str(pid) + ' - Splitting keywords...')
                keywords = ' '.join(keywords).split()
                self.log('pid:' + str(pid) + ' - Split keywords: ' + str(keywords))
            
            self.log('pid:' + str(pid) + ' - Filtering keywords...')
            
            self.log('pid:' + str(pid) + ' - Splitting composite keywords if not found in training data')
            
            keywords_ = []

######################## This for loop is unnecessary in our case because all keywords are single words ############################
            for keyword in keywords:
                keyword_split = keyword.split()
                if len(keyword_split) > 1: #bycheck el keyword lw feh space aw 3ando klmeten 
                    num_img_ids = len(self.get_imgids_with_phrase(keyword)) #hena hyloop 3la kol el data  
                                    #w yshof lw feh keyword bta3to fe el caption then brag3 kol el img ids ely feh el keyword da
                    if num_img_ids != 0:
                        keywords_ += [keyword]
                    else:
                        keywords_ += keyword_split
                else:
                    keywords_ += [keyword]

            keywords = keywords_

            self.log('pid:' + str(pid) + ' - Updated keywords:' + str(keywords_))
            
            keywords = nlp.get_filtered_keywords(keywords, self.keywords_type) #malhash lazma 5ales
            self.log('pid:' + str(pid) + ' - Filtered keywords: ' + str(keywords))

            self.log('pid:' + str(pid) + ' - Removing stopwords')
            # keywords = self.remove_stopwords(keywords)
            # keywords = list(set(keywords))
#####################################################################################################################################       
            
            g, e, min_conns = self.get_graph(keywords, n=n, neighbourhood=parents, hops=hops, split=False, pid=pid)
            self.log('pid:' + str(pid) + ' - Graph generated in: ' + str(round((time.time()-t1)/float(60),2)) + ' minutes')

            t2 = time.time()
            g = self.post_process_graph(g, keywords, pid)
            self.log('pid:' + str(pid) + ' - Graph post processed in: ' + str(round((time.time()-t2)/float(60),2)) + ' minutes')
            
            #self.visualise_graph(g, keywords)

            t3 = time.time()
            captions, log_probs, num_graph_nodes, iterations = self.traverse(g, max_iters, keywords, nlogP, optimiser, pid)
            self.log('pid:' + str(pid) + ' - Graph traversed in: ' + str(round((time.time()-t3)/float(60),2)) + ' minutes')
            
            captions_df = self.get_captions_metrics(keywords, captions, log_probs, num_graph_nodes, iterations, pid).sort_values(by=['log_prob_optimiser'], ascending=False)
            self.log('pid:' + str(pid) + ' - Total duration: ' + str(round((time.time()-t1)/float(60),2)) + ' minutes')

        except Exception as e:
            self.log('[get_captions_df()]: ' + str(e))

        return captions_df

    #pd_src_file dh array el sowar le kol process
    def process_detections(self, pd_src_file, process_id):
        not_generated_list = []    
        t = time.time()
        row_count = 0
        
        try:
            for index, row in pd_src_file.iterrows():
                img_id = row['img_id']
                keywords = row[self.keywords_column]
                
                self.log('------------------------------------------------------------------------------------------')
                self.log('pid:' + str(process_id) + ' ' + 
                         str(row_count+1) + '/' + str(len(pd_src_file))  + ' - img_id:' + 
                         str(img_id) + ' ' + self.keywords_column + ':' + str(keywords))
                self.log('------------------------------------------------------------------------------------------')

                try:
                    if not (keywords == None or keywords == '[]'):
                        keywords = eval(row[self.keywords_column]) #dlw2ty el keywords ely fo2 string 3la shakl list 
                                                        # fa eval bt5aleha actual LIST                 
                        captions = self.get_captions_df(keywords, process_id)

                        captions = captions[0:5]
                        captions.insert(loc=0, column='index', value=index)
                        captions.insert(loc=1, column='img_id', value=img_id)
                        captions.insert(loc=2, column='rank', value=np.arange(1, len(captions)+1))

                        captions.reset_index(drop=True)
                        out_csv_file = self.out_folder + '/' + 'out_' + str(process_id) + '.csv'
                        self.log('[process_detections] pid:' + str(process_id) + ' - Writing captions to ' + out_csv_file)
                        
                        if not os.path.isfile(out_csv_file):
                            captions.to_csv(out_csv_file, index=False)
                        else:
                            captions.to_csv(out_csv_file, mode='a', index=False, header=False)

                    else:
                        self.log('[CAPTION WAS NOT GENERATED]: keyword set is: ' + str(keywords))
                        not_generated_list += [str(img_id) + '- keywords']
                
                except Exception as e:
                    self.log('[CAPTION GENERATION EXCEPTION]: ' + str(e))
                    not_generated_list += [str(img_id) + '- ' + str(e)]
                
                row_count += 1

            if len(not_generated_list) != 0:
                self.log('Process:' + str(process_id) + ' - writing not generated image ids...')
                
                with open(self.out_folder + '/img_ids_not_generated_' + str(process_id) + '.txt', 'w') as f:
                    for ng in np.array(not_generated_list).flatten():
                        f.write("%s\n" % ng)
                
                f.close()  

            self.log('------------------------------------------------------------------------------------------')
            self.log('Process:' + str(process_id) +  ' duration: ' + str(round((time.time()-t)/float(60),2)) + ' minutes')
            self.log('------------------------------------------------------------------------------------------\n')
            
        except Exception as e:
            self.log('process_detections(): ' + str(e))

    def generate_captions(self):
        try:
            self.log('=======================================================')
            t = time.time()
                        
            self.log('Loading input file...')
            pd_test_detection = pd.read_csv(self.input_csv_file_path) # ely byrag3 mn de dataframe 
            pd_test_detection = pd_test_detection.replace({np.nan: None}).head(self.num_imgs) #sheel ay row feha nan w 7ot None w 5od 
                                                                                        #el rows b3ad el imags ely 3ayzha ely md5lenha ka input
                                                                                        

            # self.log(pd_test_detection.head())
            
            self.log('Total number of images to caption:' + str(len(pd_test_detection)))

            assert 'img_id' in pd_test_detection.columns, 'img_id not found in input csv columns.'
            assert self.keywords_column in pd_test_detection.columns,  self.keywords_column + ' not found in input csv columns.'

            offsets_list = []

            # getting offsets for rows to generate captions
            # for split in np.array_split([0,1,2]), 2):
            # for split in np.array_split([0,1],[2]), 2):
            
            for split in np.array_split(np.arange(len(pd_test_detection)), self.num_processes):
                offsets_list += [[split[0], split[-1]+1]]

            gen_captions = []
            not_gen_img_ids = []

            self.log('Number of processes:' + str(self.num_processes))

            # starting threads
            self.log('Starting processes..')
            
            pool = multiprocessing.Pool(processes=self.num_processes)

            for i in range(self.num_processes):
                # getting row offsets
                offsets = offsets_list[i]        
                from_row = offsets[0]
                to_row = offsets[1]
                pool.apply_async(self.process_detections, args=(pd_test_detection[from_row: to_row], i))
                                 
            pool.close()
            self.log('Waiting for processes to finish...')
            pool.join()
                
            self.log('Processes finished...')
            self.log('Combining output...')
            self.combine_output()
            
            self.log('Total duration: ' + str(round((time.time()-t)/float(60),2)) + ' minutes')
        
        except Exception as e:
            self.log('generate_captions():' + str(e))

    def combine_output(self):
        combined_pd_out = None
        combined_ids_not_generated = []
        
        for i in range(self.num_processes):
            file_path = self.out_folder + '/out_' + str(i) + '.csv'
            
            if os.path.exists(file_path):
                self.log('Combining ' + file_path)
                pd_out = pd.read_csv(file_path)
                
                if combined_pd_out is None:
                    combined_pd_out = pd_out
                else:
                    combined_pd_out = pd.concat([combined_pd_out, pd_out])
            
        if combined_pd_out is not None:
            combined_pd_out.sort_values(by=['index', 'rank']).to_csv(self.out_folder + '/out.csv', index=False)
        
        for i in range(self.num_processes):
            file_path = self.out_folder + '/img_ids_not_generated_' + str(i) + '.txt'
            if os.path.exists(file_path):
                ids_not_generated_txt = open(file_path, 'r')
                lines = ids_not_generated_txt.readlines()
                combined_ids_not_generated += lines

        combined_img_ids = open(self.out_folder + '/combined_img_ids.txt', 'w')
        combined_img_ids.writelines(combined_ids_not_generated)
        combined_img_ids.close()

    def log(self, msg):
        log_format = "%(asctime)s - %(message)s"
        logging.basicConfig(filename = self.out_folder + "/KGCap.log", filemode = "w", format = log_format,level = logging.DEBUG)
        logger = logging.getLogger()
        
        print(msg)
        logger.info(msg)
