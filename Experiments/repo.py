import git
import json
import os
import requests

import MorphoDepot

ghProgressMethod = lambda message : MorphoDepot.MorphoDepotWidget.ghProgressMethod(None, message)
logic = MorphoDepot.MorphoDepotLogic(ghProgressMethod)
logic.ghPathSearch()

accessionData = {
        '7_1': "md-test",
        '6_2': "CC BY",
        '2_1': "No",
        '3_1': "Homo sapiens",
}

repoName = accessionData['7_1']
repoDir = f"{logic.localRepositoryDirectory()}/{repoName}"

os.makedirs(repoDir)

# save data
sourceFileName = "MRHead"
n = getNode(sourceFileName)
sourceFilePath = f"{repoDir}/MRHead.nrrd"
slicer.util.saveNode(n, sourceFilePath)
t = getNode("Labels")
slicer.util.saveNode(t, f"{repoDir}/Labels.ctbl")

# write accessionData file
fp = open(f"{repoDir}/MorphoDepotAccession.json", "w")
fp.write(json.dumps(accessionData))
fp.close()

# write license file
if accessionData["6_2"].startswith("CC BY-NC"):
    licenseURL = "https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt"
else:
    licenseURL = "https://creativecommons.org/licenses/by/4.0/legalcode.txt"
response = requests.get(licenseURL)
fp = open(f"{repoDir}/LICENSE.txt", "w")
fp.write(response.content.decode())
fp.close()

# write readme file
fp = open(f"{repoDir}/README.md", "w")
fp.write(f"""
Repository for segmentation of a specimen scan.  See [this file](MorphoDepotAccession.json) for details.
""")
fp.close()

# create readme
repo = git.Repo.init(repoDir)

repo.index.add([f"{repoDir}/README.md",
                f"{repoDir}/LICENSE.txt",
                f"{repoDir}/MorphoDepotAccession.json",
                f"{repoDir}/Labels.ctbl",
])
repo.index.commit("Initial commit")

logic.gh(f"repo create {repoName} --add-readme --disable-wiki --private --source {repoDir} --push")

logic.localRepo = repo
repoNameWithOwner = logic.nameWithOwner("origin")

logic.gh(f"repo edit {repoNameWithOwner} --enable-projects=false --enable-discussions=false")

if accessionData['2_1'] == "Yes":
    idigbioURL = accessionData['2_2']
    specimenID = idigbioURL.split("/")[-1]
    import idigbio
    api = idigbio.json()
    idigbioData = api.view("records", specimenID)
    speciesString = idigbioData['data']['ala:species']
else:
    speciesString = accessionData['3_1']
speciesString = speciesString.lower().replace(" ", "-")

logic.gh(f"repo edit {repoNameWithOwner} --add-topic morphodepot --add-topic md-{speciesString}")

logic.gh(f"release create --repo {repoNameWithOwner} v1 --notes Initial-release")
logic.gh(f"release upload --repo {repoNameWithOwner} v1 {sourceFilePath}")

# write source volume
fp = open(f"{repoDir}/source_volume", "w")
fp.write(f"https://github.com/{repoNameWithOwner}/releases/download/v1/{sourceFileName}")
fp.close()

repo.index.add([f"{repoDir}/source_volume"])
repo.index.commit("Add source file url file")
repo.remote(name="origin").push()
