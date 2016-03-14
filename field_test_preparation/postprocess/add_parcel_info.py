#!/usr/bin/env python
import argparse
import pandas as pd
import os

def main():
    path_to_postprocess = os.path.join(os.environ['OUTPUT_FOLDER'], 'postprocess')
    path_to_parcel_info = os.path.join(path_to_postprocess, "parcel_info.csv")
    predictions = args.predictions_file
    output = '{}_details.csv'.format(predictions.replace('.csv', ''))

    try:
        parcel_info = pd.read_csv(path_to_parcel_info, index_col=0)
    except:
        raise IOError(("Couldn't load parcels info file from {}. Make sure you run "
            "download_parcel_info.py first to generate the file ".format(path_to_parcel_info)))

    to_inspect = pd.read_csv(predictions, header=None, index_col=0)
    to_inspect = pd.merge(to_inspect, parcel_info, how='left', left_index=True, right_index=True)
    to_inspect["last_inspection"] = pd.to_datetime(to_inspect["last_inspection"])
    to_inspect.to_csv(output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=("Adds parcel info to a csv file with "
        "parcel_id as its first column. Must run download_parcel_info.py "
        "first to download parcel data from the database."))
    parser.add_argument("predictions_file",
                        help=("Path to file containing predictions, must "
                              "contain parcel_id and should be the first column"),
                        type=str)
    args = parser.parse_args()
    main()
