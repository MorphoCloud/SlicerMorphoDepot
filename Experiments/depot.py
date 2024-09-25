import git
import github
import os
import random

ghUser = "pieper923"
tokenPath = "/home/exouser/.ssh/pieper923-MD_E15-token"
repoToken = open(tokenPath).read().strip()

repository = "pieper/MD_E15"
repositoryURL = f"https://{repoToken}@github.com/{repository}"
repositoryPullURL = f"https://github.com/{repository}/pull"
repoDirectory = "/home/exouser/Documents/MD_E15"

gh = github.Github(repoToken)
ghRepo = gh.get_repo(repository)

if os.path.exists(repoDirectory):
    localRepo = git.Repo(repoDirectory)
else:
    localRepo = git.Repo.clone_from(repositoryURL, repoDirectory)
print(localRepo)

issues = ghRepo.get_issues(assignee=ghUser)
issue = issues.get_page(0)[0] # TODO: user picks from a list of issues
print(f"You should work on: {issue.title}")
issueNumber = issue.number
branchName=f"{issueNumber}-depot-branch"

issueBranch = None
for branch in localRepo.branches:
    if branch.name == branchName:
        issueBranch = branch
        break

if not issueBranch:
    localRepo.git.checkout("HEAD", b=branchName)
else:
    localRepo.git.checkout(branchName)


volumePath = f"{localRepo.working_dir}/master_volume"
volumeURL = open(volumePath).read().strip()
print(volumeURL)
nrrdPath = slicer.app.temporaryPath+"/volume.nrrd"
slicer.util.downloadFile(volumeURL, nrrdPath)
volume = slicer.util.loadVolume(nrrdPath)

# TODO: need way to identify segmentation
segmentationPath = f"{localRepo.working_dir}/IMPC_sample_data.seg.nrrd"
segmentation = slicer.util.loadSegmentation(segmentationPath)

# pretend to have edited the segmentation...
pass

slicer.util.saveNode(segmentation, segmentationPath)

message = f"Example change to the segmentation {random.randint(1,10000)}"
localRepo.index.commit(message)
localRepo.remote("origin").push(branchName)

body = '''
Example of some segmentation work
'''
pullRequest = ghRepo.create_pull(base='main', head=branchName, title="Segmentation work", body=body)

prURL = f"{repositoryPullURL}/{pullRequest.number}"
qt.QDesktopServices.openUrl(qt.QUrl(prURL))
