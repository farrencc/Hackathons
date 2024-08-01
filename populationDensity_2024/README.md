# Population Density Hackathon information

### Init
You'll find left over original init code in density_map.ipynb and the original data files in the TPSA Committee google drive under the 2023/24 Hackathon folder. I'm leaving the code in here just in case something breaks but I want to write a script that will auto convert from the base data files to the final gdf given as `data_file.geojson`. Since this file is larger than 100mb - this will also have to be stored in the drive. Though, on the actual day I plan on running a http server on my machine that has the geojson file. Participants will then be able to use `wget` to download the geojson without issue. __(Hopefully)__.

### Information about dataframe

All of the columns of the dataframe are given here:

0   ED_ID                 The ID for each ED as given by the state iirc\     
1   ENGLISH               Name of the ED in English\
2   GAEILGE               Name of the ED in Irish\
3   CONTAE                Resident County in English\
4   COUNTY                Resident County in Irish\
5   PROVINCE              Resident Province\
6   GUID_x                Used for geo info\
7   CENTROID_X            Used for geo info\
8   CENTROID_Y            Used for geo info\
9   AREA                  The Area of the ED in $m^2$\
10  ESRI_OID              Used for geo info\
11  Shape__Area           Area of the ED as used in the geo utils\
12  Shape__Length         Perimeter (I think) of tbe ED as used in the geo utils\
13  CSOED_3409            CSO info - might be useful for matching ED's to CSO data\
14  Electoral_Division    More thorough address \
15  VALUE                 Population of the ED\
16  GUID_y                Used for geo info\
17  Area_HA               Area of the ED in Hectares\
18  density               **IMPORTANT** Population Density of the ED measured in __$$\ln\frac{\text{Population}}{\text{Area [HA]}}$$__\
19  geometry              Used for geo info