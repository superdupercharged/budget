import sys
import os
import pandas as pd
from termcolor import colored
from jinja2 import Template

import budget_functions as bf

#TODO alle Umsatzarten berücksichtigen

args = sys.argv
df_booking = pd.read_csv('statements/'+ args[1] +'_statement.CSV',
                sep=';',
                # names=['Buchungstag','Umsatzart','Buchungstext','Betrag','IBAN Auftraggeberkonto'],
                usecols=[0, 2, 3, 4, 8])

# df_booking = df.loc[df['Umsatzart'].isin(['Lastschrift'])] # nur Lastschrift filtern
df_pop = df_booking.loc[df_booking['Umsatzart'].isin(['Zinsen/Entgelte'])]
pop_row = 0
for index, row in df_pop.iterrows():
    if "Thilo Bleumer" in row['Buchungstext']:
        continue
    df_booking = df_booking.drop(index)
    pop_row += 1

df_booking_unknown = df_booking.copy()
budget = bf.budget()
category_names = list(budget.categories_dict.keys())
category_sums = []
evaluation = []
for i in range(len(category_names)):
    evaluation.append({})

def update_evaluation():
    if alias in evaluation[category_index]:
        evaluation[category_index][alias] = evaluation[category_index][alias] + (float(row['Betrag'].replace(',','.')))
    else:
        evaluation[category_index][alias] = (float(row['Betrag'].replace(',','.')))

def category_names_with_index(_category_names):
    _category_names = _category_names.copy()
    for i in range(len(_category_names)):
        _category_names[i] = '(' + str(i) + ')' + _category_names[i]
    return _category_names

for index, row in df_booking.iterrows():
    if budget.search_category(row['Buchungstext']) is not False:
        category_name, alias = budget.search_category(row['Buchungstext'])
        category_index = category_names.index(category_name)
        update_evaluation()
            
        df_booking_unknown = df_booking_unknown.drop(index)

for dict in evaluation:
    category_sums.append(sum(dict.values()))

print(f"""#################################################################
########    The statement has {df_booking_unknown.shape[0]} unclassified bookings   #########
#################################################################\n""")

continue_indices = []
print(category_names)
category_names_prompt = category_names_with_index(category_names)
for index, row in df_booking_unknown.iterrows():
    if index in continue_indices:
        print('continue indices: ', continue_indices)
        continue
    category_index = input(f"""Choose a category for this transaction: ({category_names_prompt})
            
    #         ==> {row['Buchungstext']} <==
    #         ==> {row['Betrag']} € <==
    #         ---> """)
    if category_index == 'skip':
        continue
    #TODO catch other strings!
    category_index = int(category_index)
    if category_index >= len(category_names):
        category_index = input(colored(f"""Please choose a VALID category index (0 ... {len(category_names)-1})
    #         ---> """, "yellow"))
        
    alias = input("... and an alias please: ")
    update_evaluation()
    
    df_booking_unknown = df_booking_unknown.drop(index)
    if alias == 'once':
        update_evaluation()
        continue
    
    budget.add_save_categories_dict(category_index, alias)
    
    counter_repeated_booking_text = 0
    for index, row in df_booking_unknown.iterrows():
        if alias in row['Buchungstext']:
            update_evaluation()
            
            df_booking_unknown = df_booking_unknown.drop(index)
            continue_indices.append(index)
            counter_repeated_booking_text += 1
    print(f'Found {counter_repeated_booking_text} bookings with {alias} in text')
    counter_repeated_booking_text = 0

    print(f'{df_booking_unknown.shape[0]} unclassified bookings are left')

total_in, total_out = 0, 0
for dict in evaluation:
    category_sums.append(sum(dict.values())) # TODO kommutativgesetz savings?!, other stimmt nicht?
for i in category_sums[:2]:
    total_in = total_in + i
for i in category_sums[2:]:
    total_out = total_out + i

# print(df.loc[0])

# define a template
template = Template("""
{{ title }}
SUM: {{ total_out_cat|round(2) }} €
{% for key, value in data.items() -%}
- {{ key }}: {{ (value)|round(2) }} €
{% endfor %}
""")

file_name = 'evaluation/overview_' + args[1] + '.txt' # TODO better chronological naming
if os.path.exists(file_name):
    os.remove(file_name)
with open(file_name, "w") as f:
    f.write('##################\n')
    f.write('# OVERVIEW ' + args[1].upper() +' #\n')
    f.write('##################\n')
    f.write('TOTAL IN: '+ str(round(total_in,2)) + ' €'+'\n')
    f.write('TOTAL OUT: '+ str(round(total_out,2)) + ' €'+'\n'+'\n')

for i in range(len(evaluation)):
    document = template.render(title=category_names[i].upper(), data=evaluation[i], total_out_cat=category_sums[i])
    with open(file_name, 'a') as f:
        f.write(document)
