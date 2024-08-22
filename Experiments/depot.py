import git
import github
import os
import random

tokenPath = "/home/exouser/.ssh/pieper923-MD_E15-token"
repoToken = open(tokenPath).read().strip()

repository = "pieper923/MD_E15"
repositoryURL = f"https://{repoToken}@github.com/{repository}"
repositoryPullURL = f"https://github.com/{repository}/pull"
repoDirectory = "/home/exouser/Documents/MD_E15"


if os.path.exists(repoDirectory):
    localRepo = git.Repo(repoDirectory)
else:
    localRepo = git.Repo.clone_from(repositoryURL, repoDirectory)
print(localRepo)

volumePath = f"{localRepo.working_dir}/master_volume"
volumeURL = open(volumePath).read().strip()
print(volumeURL)
nrrdPath = slicer.app.temporaryPath+"/volume.nrrd"
slicer.util.downloadFile(volumeURL, nrrdPath)
volume = slicer.util.loadVolume(nrrdPath)

# TODO: need way to identify segmentation
segmentationPath = f"{localRepo.working_dir}/IMPC_sample_data.seg.nrrd"
segmentation = slicer.util.loadSegmentation(segmentationPath)

workBranch = localRepo.create_head("work")
workBranch.checkout()

# pretend to have edited the segmentation...
pass

slicer.util.saveNode(segmentation, segmentationPath)

message = f"Example change to the segmentation {random.randint(1,10000)}"
localRepo.index.commit(message)
localRepo.remote("origin").push('work')

gh = github.Github(repoToken)
ghRepo = gh.get_repo(repository)
body = '''
Example of some segmentation work
'''
pullRequest = ghRepo.create_pull(base='main', head='work', title="Segmentation work", body=body)

prURL = f"{repositoryPullURL}/{pullRequest.number}"
qt.QDesktopServices.openUrl(qt.QUrl(prURL))
