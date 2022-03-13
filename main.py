from flask import Flask, request
import dataclasses
import json
from typing import Any
import urllib.parse
import requests
import mwparserfromhell
import time
import threading


default_chest_costs = dict(
    Wood={7: 0},
    Gold={1: 25_000, 2: 50_000, 7: 100_000},
    Diamond={1: 50_000, 2: 100_000, 7: 250_000},
    Emerald={1: 100_000, 2: 250_000, 7: 500_000},
    Obsidian={1: 250_000, 2: 500_000, 7: 1_000_000},
    Bedrock={4: 4, 7: 2_000_000}
)


@dataclasses.dataclass
class DungeonDrop:
    item: str
    floor: int
    chest: str
    cost: int
    drop_chances: dict

    def get_drop_chance(self, has_s_plus: bool, talisman_level: int, boss_luck: int):
        drop_identifier = "S" + ("+" if has_s_plus else "") + "ABCD"[
            talisman_level] + str(len([i for i in [0, 1, 3, 5, 10] if i >= boss_luck]))
        return self.drop_chances.get(drop_identifier)


class ObjectEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o):
            return o.__dict__
        return super().default(o)


def fetch_dungeon_loot():
    titles = [f"Template:Catacombs Floor {f} Loot" for f in [
        "I", "II", "III", "IV", "V", "VI", "VII"]]
    titles.extend([f"Template:Catacombs Floor {f} Loot Master" for f in [
                  "I", "II", "III", "IV", "V", "VI", "VII"]])
    items = {}
    for title, floor in get_wiki_sources_by_title(*titles).items():
        floor_num = -1
        floor_data = {}
        for template in floor.filter_templates():
            if template.name.strip() == "Dungeon Chest Table/Row":
                item = None
                ifloor = None
                chest = None
                cost = 0
                drop_chances = {}

                for param in template.params:
                    attr_name = param.name.nodes[0].strip()
                    attr_value = param.value.nodes[0].strip()
                    if attr_name == "item":
                        if item is None:
                            item = attr_value.replace("Ultimate_Jerry", "Ultimate Jerry").replace("Ultimate One For All", "One For All").replace(
                                "One For All", "One For All I").replace("’", "'")
                            if item.startswith("Wise "):
                                item = "Ultimate " + item
                            elif item.startswith("Master Skull - Tier "):
                                item = "Master Skull - Tier " + \
                                    str(item.split(
                                        "Master Skull - Tier ")[1].count("I"))
                            elif item.endswith(" Pet"):
                                item = item.split(" Pet")[0]
                    elif attr_name == "chest":
                        chest = attr_value
                    elif attr_name == "cost":
                        cost = int(attr_value)
                    elif attr_name == "floor":
                        ifloor = int(attr_value)
                        if title.endswith("Master"):
                            ifloor += 7
                        floor_num = ifloor
                    elif attr_name.startswith("S"):
                        drop_chances[attr_name] = attr_value
                if item is None or ifloor is None or chest is None:
                    print("WARNING: Missing data for item: " + str(template))
                else:
                    if cost == 0:
                        defaults = default_chest_costs[chest]
                        cost = defaults[min(
                            f for f in defaults.keys() if f >= (ifloor-7 if title.endswith("Master") else ifloor))]

                    if(chest not in floor_data.keys()):
                        floor_data[chest] = []
                    floor_data[chest].append(DungeonDrop(
                        item, ifloor, chest, cost, drop_chances))
        items[floor_num] = floor_data
    return items


def get_wiki_sources_by_title(*page_titles: str, wiki_host: str = "wiki.hypixel.net"):
    prepared_titles = "|".join(map(urllib.parse.quote, page_titles))
    api_data = requests.get(
        f"https://{wiki_host}/api.php?action=query&prop=revisions&titles={prepared_titles}&rvprop=content&format=json&rvslots=main").json()
    if "batchcomplete" not in api_data:
        print(f"Batch data not present in wiki response for: {page_titles}")

    return {
        page["title"]: mwparserfromhell.parse(
            page["revisions"][0]["slots"]["main"]["*"])
        for _, page in api_data["query"]["pages"].items()
    }


def update_data():
    data = fetch_dungeon_loot()
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=ObjectEncoder)


app = Flask("app")


@app.route("/")
def home():
    return {"deez": "nuts"}


@app.route("/data")
def data():
    args = request.args

    floor = 0
    try:
        floor = int(args["floor"])
    except ValueError:
        pass
    if floor < 1 or floor > 14:
        return {"cause": "Invalid"}

    with open("data.json") as file:
        return json.load(file)[str(floor)]


@app.before_first_request
def activate_job():
    def run_job():
        while True:
            print("Updating data")
            update_data()
            print("Data updated")
            time.sleep(3600)

    thread = threading.Thread(target=run_job)
    thread.start()


app.run(host="0.0.0.0", port=8081)
