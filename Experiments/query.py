import glob
import json
import os
import requests

import MorphoDepot
logic = MorphoDepot.MorphoDepotLogic()
repos = logic.morphoRepos()

repoDirectory = os.path.normpath(slicer.util.settingsValue("MorphoDepot/repoDirectory", "") or "")

searchDirectory = f"{repoDirectory}/MorphoDepotSearchCache"
os.makedirs(searchDirectory, exist_ok=True)

repoDataByNameWithOwner = {}

for repo in repos:
    repoName = repo['name']
    ownerLogin = repo['owner']['login']
    nameWithOwner = f"{repoName}-{ownerLogin}"
    filePath = f"{searchDirectory}/{nameWithOwner}-MorphoDepotAccession.json"
    if os.path.exists(filePath):
        fp = open(filePath)
        repoDataByNameWithOwner[nameWithOwner] = json.loads(fp.read())
    else:
        urlPrefix = "https://raw.githubusercontent.com"
        urlSuffix = "refs/heads/main/MorphoDepotAccession.json"
        accessionURL = f"{urlPrefix}/{ownerLogin}/{repoName}/{urlSuffix}"
        request = requests.get(accessionURL)
        if request.status_code == 200:
            fp = open(filePath, "w")
            fp.write(request.text)
            fp.close()
            repoDataByNameWithOwner[nameWithOwner] = json.loads(request.text)

print(repoDataByNameWithOwner.keys())
