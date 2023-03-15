import json

budget_categories = {
    'rent':['RAUSCH'],
    'life':['STAIB','LIDL','MCDONALDS','RUNDFUNK'],
    'car':['Ran-TSUlm'],
    'fun':['BAD BLAU','SPIELBURG'],
    'house':['IKEA','Depot','BAUHAUS'],
    'clothes':['ZALANDO'],
    'holidays':['Center Parcs'],
    'other':[]
}

with open('budget_dict.json', 'w') as f:
    json.dump(budget_categories, f)


with open('budget_dict.json', 'r') as f:
    my_dict = json.load(f)

print(my_dict)
