#Cincinnati project

This is the continuation of the Cincinnati [summer project](https://github.com/dssg/cincinnati2015) done during DSSG 2015.

#About

First settled in 1788, Cincinnati is one of the oldest American cities west of the original colonies. Today, the 
city struggles with aging home stock, stifling economic redevelopment in some neighborhoods. 

DSSG is working with the City of Cincinnati to identify properties at risk of code violations or abandonment. We hope
that early intervention strategies can prevent further damage and stimulate neighborhood revitalization. Read more about
our project [here](http://dssg.uchicago.edu/2015/08/20/cincy-blight-prevention.html). 

#Setup

##Select one folder for the data and another for the code

The code relies on two environment variables, before you start running the code, decide where are you going to store the *raw data* and the *code*.

Then add these two environment variables:

`export ROOT_FOLDER="/absolute/path/to/the/repo"`

`export DATA_FOLDER="/absolute/path/to/the/raw/data"`

Consider adding that to your profile so it gets loaded every time you log in.

##Clone the repo

`git clone https://github.com/dssg/cincinnati $ROOT_FOLDER`

##Put the data following the repo structure

The pipeline follows certain simple conventions to make the code easy to understand. It is assumed that a file in `$ROOT_FOLDER/etl/something/` will get its raw data from `$DATA_FOLDER/etl/something/`.

Having, said that it's easy to know where to store the raw data. For example, the code that loads all taxes data is `$ROOT_FOLDER/etl/taxes/taxes.sh`, then, your raw taxes files should be stores in `$DATA_FOLDER/etl/taxes/`

The other convention is that intermediate files are stored on a `tmp/` folder, for example, since we need to preprocess the taxes files before uploading them to the database, the intermediate csv files will be on `$DATA_FOLDER/etl/taxes/tmp/`.

##Provide config.yaml and .pgpass

The code loads some parameters from a `config.yaml` file stored in the `$ROOT_FOLDER`.

Use the `config_sample.yaml` file to see the structure and then rename it to `config.yaml`, make sure that the file is stores in your `$ROOT_FOLDER`.


##Build docker ETL image

The ETL step depends on these programs:

* Python 2.7.11
* GDAL 1.11.2
* Java 1.8
* sql (PostgreSQL) 9.3.10
* mdbtools 0.7.1 
* gnumeric 1.12.9
* stanford-ner-2015-12-09
* ...and many Ptyhon packages

To ease the setup, a Dockerfile is provided which builds an Ubuntu 14.04 image with all dependencies included and properly configured.

Most dependencies are needed for the ETL step, after the raw data is on the database, only Python (and a few packages) and psql is needed, hence, if you want, you can use the Docker image for the ETL phase.

For information on how to setup Docker, see the [official docs](https://docs.docker.com/).

Once Docker is properly setup, go to your `$ROOT_FOLDER` and run:

`docker build -t cincinnati .`

This process takes a long time since it needs to download and install all dependencies, but with a decent internet connection is should take less than 1 hour.

##Run docker image

Once the image is ready, run it: 

`docker run -v $DATA_FOLDER:/root/data -v $ROOT_FOLDER:/root/code -i -t cincinnati /bin/bash`

Note that we are passing our two environment variables, and linking them to two folders inside the container. The purpose of the Docker container is to run code but not to store anything (not code and of course, not data).

---
This part is still work in progess... Ignore the rest of the file.

##Run the ETL

##Create features from the data

... see the blight_risk_prediction directory

## Run the modeling pipeline

##Create output directories

    mkdir results
    mkdir predictions
    
##Configure the model

    edit default.yaml (options are documented in default.yaml)
    
##Run the model

    python -m blight_risk_prediction/model
   
#### Output

Each model run produces a pickle file which contains:

* the full list of parcels predicted to have violations
* the configuration file used to generate that model
* feature importances

These output files include a timestamp in their filename such that they will not be accidentally overwritten. These files can be used with the evaluation web application in `evaluation`. 

## Repository layout

* blight_risk_prediction - our modeling pipeline
* docs - some additional documentation
* etl - scripts for loading the Cincinnati datasets into a postgres database
* evaluation - webapp we use for comparing different models
* postprocess - add details (e.g. address) about properties to predictions
* targeting_priority - re-rank predictions according to some targeting priority
* test - unit tests

