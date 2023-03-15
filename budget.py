import sys
import pandas as pd
from termcolor import colored

import budget_functions as bf

args = sys.argv
print(args)
df = pd.read_csv('statements/'+ args[1],
                sep=';',
                # names=['Buchungstag','Umsatzart','Buchungstext','Betrag','IBAN Auftraggeberkonto'],
                usecols=[0, 2, 3, 4, 8])

df_Lastschrift = df.loc[df['Umsatzart'].isin(['Lastschrift'])] # nur Lastschrift filtern
df_Lastschrift_unknown = df_Lastschrift.copy()
budget = bf.budget()
category_names = list(budget.categories_dict.keys())
category_sums = [0.0]*len(category_names)


for index, row in df_Lastschrift.iterrows():
    if budget.search_category(row['Buchungstext']) is not False:
        category_index = category_names.index(budget.search_category(row['Buchungstext']))
        category_sums[category_index] = category_sums[category_index] - float(row['Betrag'].replace(',','.'))
        # print(index, budget.search_category(row['Buchungstext']), category_sums[category_index])
        df_Lastschrift_unknown = df_Lastschrift_unknown.drop(index)
print(f"""Overview
{category_names}
{category_sums}

""")
print(f'The statement has {df_Lastschrift_unknown.shape[0]} unclassified bookings')

continue_indices = []
for index, row in df_Lastschrift_unknown.iterrows():
    # print('current index: ', index)
    if index in continue_indices:
        print('continue indices: ',continue_indices)
        continue
    category_index = input(f"""Choose a category for this transaction: ({category_names})
            
    #         ==> {row['Buchungstext']} <==
    #         ==> {row['Betrag']} € <==
    #         ---> """)
    if category_index == 'skip':
        continue
    else:
        category_index = int(category_index)
    
    if category_index > len(category_names):
        category_index = input(colored(f"""Please choose a VALID category index (0 ... {len(category_names)})
    #         ---> """, "yellow"))
        
    alias = input("... and an alias please: ")
    category_sums[category_index] = category_sums[category_index] - float(row['Betrag'].replace(',','.'))
    df_Lastschrift_unknown = df_Lastschrift_unknown.drop(index)
    if alias == 'once':
        continue
    budget.add_save_categories_dict(category_index, alias)
    

    counter_repeated_booking_text = 0
    for index, row in df_Lastschrift_unknown.iterrows():
        if alias in row['Buchungstext']:
            category_sums[category_index] = category_sums[category_index] - float(row['Betrag'].replace(',','.'))
            df_Lastschrift_unknown = df_Lastschrift_unknown.drop(index)
            continue_indices.append(index)
            counter_repeated_booking_text += 1
    print(f'Found {counter_repeated_booking_text} bookings with {alias} in text')
    counter_repeated_booking_text = 0

    print(f"""Overview
    {category_names}
    {category_sums}

    """)

    print(f'{df_Lastschrift_unknown.shape[0]} unclassified bookings are left')

    
# print(category_names)
# print(category_sums)
# print(df.loc[0])

def search_str_in_col(my_str):
    df_filtered = df[df['Buchungstext'].str.contains(my_str)]
    print(df_filtered.head())