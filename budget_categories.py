"""Seed / reference for budget category names (do not run casually — overwrites budget_dict.json)."""
import json

budget_categories = {
    "income": [],
    "housing": ["RAUSCH"],
    "food": ["STAIB", "LIDL", "MCDONALDS"],
    "mobility": ["Ran-TSUlm"],
    "life": ["RUNDFUNK"],
    "fun": ["BAD BLAU", "SPIELBURG"],
    "shopping": ["IKEA", "Depot", "BAUHAUS", "ZALANDO"],
    "holidays": ["Center Parcs"],
    "savings": [],
    "car_loan": [],
    "house_loan": [],
    "wuestenrot": [],
    "tithe": [],
    "transfers": [],
    "other": [],
}

if __name__ == "__main__":
    with open("budget_dict.json", "w", encoding="utf-8") as f:
        json.dump(budget_categories, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(budget_categories)
