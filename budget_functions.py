import json

class budget():
    def __init__(self):
        with open('budget_dict.json', 'r') as f:
            self.categories_dict = json.load(f)
        self.category_names = list(self.categories_dict.keys())

    def search_category(self, Buchungstext):
        for category_name in self.category_names:
            for value in self.categories_dict[category_name]:
                if value.lower() in Buchungstext.lower():
                    return category_name
        return False
    
    def get_categories_sum(self):
        pass

    def add_save_categories_dict(self, index, alias):
        self.categories_dict[self.category_names[index]].append(alias)
        with open('budget_dict.json', 'w') as f:
            json.dump(self.categories_dict, f)
    
    # for index, row in df_Lastschrift.iterrows():
    #     key_input = input(f"""Choose a key for this transaction: ({budget_category.keys()})
            
    #         ==> {row['Buchungstext']} <==
    #         ---> """)
    #     while budget_category.get(key_input) is None:
    #         key_input = input(colored("""Please choose a VALID key
    #         ---> """, "yellow"))
    #     alias = input("... and an alias please: ")
    #     budget_category[key_input].append({row['Buchungstext'][:20]: alias}) # TODO cut the string before numbers?
    #     print(budget_category)
    #     df_filtered = df_Lastschrift[df_Lastschrift['Buchungstext'].str.contains(alias)]
    #     print('Number of objects with this alias:', len(df_filtered))
            
