FROM ubuntu:trusty
MAINTAINER Eduardo Blancas Reyes

#Run everything with bash instead of sh
RUN rm /bin/sh && ln -s /bin/bash /bin/sh

#Set a better PS1
RUN echo 'export PS1="\[\e[0;31m\]\u\[\e[m\] \[\e[1;34m\]\w\[\e[m\] \[\e[0;31m\]$ \[\e[m\]\[\e[0;32m\]"' >> /root/.bashrc

#Setup project env variables
ENV ROOT_FOLDER=/root/code
ENV DATA_FOLDER=/root/data
ENV OUTPUT_FOLDER=/root/output
ENV PYTHONPATH=$PYTHONPATH:$ROOT_FOLDER/lib_cinci

#Install wget and unzip
RUN apt-get -qq update
RUN apt-get install -y wget
RUN apt-get install -y unzip

#Install Python 2.7 via miniconda
RUN wget https://repo.continuum.io/miniconda/Miniconda-latest-Linux-x86_64.sh -O /root/miniconda.sh
RUN bash /root/miniconda.sh -b -p /root/miniconda
RUN rm /root/miniconda.sh
ENV PATH="/root/miniconda/bin:$PATH"

#Install common packages
RUN apt-get install -y software-properties-common
#Add repository for gdal
RUN add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable
#Add repo for java 8
RUN add-apt-repository -y ppa:webupd8team/java
RUN apt-get update

#Install GDAL
RUN apt-get install -y gdal-bin
#Install development packages to make Geopandas work
RUN apt-get install -y --force-yes libgdal-dev

#Install PostGIS (to get shp2pgsql)
RUN apt-get install -y postgis

#Auto accept oracle license and install required java version for NER (Java 1.8 or later)
RUN echo oracle-java8-installer shared/accepted-oracle-license-v1-1 select true | sudo /usr/bin/debconf-set-selections
RUN apt-get install -y oracle-java8-installer

#Install postgresql (only client)
RUN apt-get -y install postgresql-client

#Install mdbtools to convert access databases to csv files
RUN apt-get install -y mdbtools

#Install gnumeric to use ssconvert, which lets convert xls files to csv
RUN apt-get install -y gnumeric
 
#Install Stanford's NER
#http://nlp.stanford.edu/software/CRF-NER.shtml#Download
WORKDIR /root
ENV NAME="stanford-ner-2015-12-09"
RUN wget http://nlp.stanford.edu/software/$NAME.zip
RUN unzip $NAME.zip
RUN rm -rf $NAME.zip
#Define CLASSPATH and path to the NER classifiers
ENV CLASSPATH=/root/$NAME/stanford-ner.jar
ENV NER_CLASSIFIERS=/root/$NAME/classifiers

# also need some dependencies for NER
RUN wget http://nlp.stanford.edu/software/stanford-corenlp-full-2015-12-09.zip
RUN unzip stanford-corenlp-full-2015-12-09.zip
RUN rm stanford-corenlp-full-2015-12-09.zip
ENV CLASSPATH=$CLASSPATH:/root/stanford-corenlp-full-2015-12-09/stanford-corenlp-3.6.0.jar:/root/stanford-corenlp-full-2015-12-09/slf4j-simple.jar:/root/stanford-corenlp-full-2015-12-09/slf4j-api.jar

#Copy the conda requirements file
COPY environment.yml /tmp/

#Install Python dependencies
RUN conda env create --file /tmp/environment.yml

#Install Python3 environment with some dependencies (this is required to run the NER code)
#https://www.continuum.io/content/python-3-support-anaconda
RUN conda create -n py3 python=3 pandas sqlalchemy pyyaml psycopg2 pip
RUN source activate py3

#Copy .pgpass
COPY $ROOT_FOLDER/.pgpass /root/
RUN chmod 0600 /root/.pgpass

#Automatically start cincinnati conda environment
RUN echo 'source activate cincinnati' >> /root/.bashrc
