--Join parcel column in eac inspection in
--parcels_inspection (in whatever it is the current schema)
--with addresses that are within 1Km (using parcel2address table)
--then filter those addreses for events within 3 month of
--inspection date

--This script is intended to be used as a template for various tables
CREATE TABLE IF NOT EXISTS events_3months_$TABLE_NAME AS (
    SELECT
        insp.parcel_id, insp.inspection_date,
        p2a.dist_km,
        $TABLE_NAME.*
    FROM parcels_inspections AS insp
    JOIN public.parcel2address AS p2a
    USING (parcel_id)
    JOIN public.address
    ON address_id=address.id
    JOIN public.$TABLE_NAME
    ON address.address=$TABLE_NAME.address --THIS IS SLOW, maybe change for an ID or simply add index
    AND (insp.inspection_date - '3 month'::interval) <= $TABLE_NAME.$DATE_COLUMN
    AND $TABLE_NAME.$DATE_COLUMN <= insp.inspection_date
);

