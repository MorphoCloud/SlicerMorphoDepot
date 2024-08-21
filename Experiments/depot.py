import git
import github
import os

username = "pieper923"
password = "REDACTED"
repository = "pieper923/MD_E15"
repositoryURL = "git@github.com:" + repository
repoDirectory = "/home/exouser/Documents/MD_E15"
keyFile = "/home/exouser/.ssh/id_ed25519"
keyTitle = "MorphoDepot-key"

authorization = github.Auth.Login(username,password)
gh = github.Github(auth=authorization)
ghRepo = gh.get_repo(repository)

if os.path.exists(repoDirectory):
    localRepo = git.Repo(repoDirectory)
else:
    if not os.path.exists(keyFile):
        print("need to set up github keys")
        result = os.system(f"ssh-keygen -t ed25519 -C {username} -N '' -f {keyFile}")
        if result != 0:
            print("Couldn't create key")
        publicKey = open(f"{keyFile}.pub").read().strip()
        print(publicKey)
        ghKey = ghRepo.create_key(keyTitle, publicKey)
        print(ghKey)

    shouldWorkButDoesNot = """
    clone_env = {"GIT_SSH_COMMAND": f"ssh -i {keyFile}"}
    try:
        localRepo = git.Repo.clone_from(repositoryURL, repoDirectory, env=clone_env)
    except git.exc.GitCommandError:
        print("could not clone : (")
    """
    command = f"GIT_SSH_COMMAND='ssh -i {keyFile}' git clone {repositoryURL} {repoDirectory}"
    result = os.system(command)
    if result != 0:
        print("could not clone : (")
    localRepo = git.Repo(repoDirectory)

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

localRepo.index.commit("Example change to the segmentation")
localRepo.remote("origin").push('work')

body = '''
Example of some segmentation work
'''
pullRequest = ghRepo.create_pull(base='main', head='work', title="Segmentation work", body=body)

#localRepo.heads['main'].checkout()

