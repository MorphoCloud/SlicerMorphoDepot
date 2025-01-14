![SlicerMorphoDepotIcon](https://github.com/user-attachments/assets/e1bc35d5-af0e-43aa-a224-417e13e6d78d)


# SlicerMorphoDepot
Experiments and implementations related to the SlicerMorph MorphoDepot project.

The goal is to use github infrastructure to manage multi-person segmentation projects.  A repository is used to manage segmentation of a specimen (e.g. a microCT of a fish) and issues are assigned to people to work on parts of the segmentation.  Pull requests are used to manage review and integration of segmentation tasks.

The Slicer extension uses git behind the scenes, but most of the project management is done from within Slicer.

See [documentation here](https://github.com/MorphoCloud/MorphoDepotDocs)

**MorphoDepot** module lists pending issues assigned to this user and allows you to load/segment/commit them and then request review.

![image](https://github.com/user-attachments/assets/2d81e4f3-8d8b-49e4-97f4-f906053d375f)

**MorphoDepotReview** module lists pending pull requests and allows PI to accept edits or request changes.

**MorphoDepotAccession (TBD)** module will allow generating github repositories that can be accessed via MorphoDepot module. 

![image](https://github.com/user-attachments/assets/9481ce0f-dc37-4900-9cdc-14bb0922df59)

# Funding 

MorphoDepot module is supported by funding from National Science Foundation (DBI/2301405). 
