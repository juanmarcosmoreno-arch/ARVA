# geNomad fixtures — CONSTRUCTED, not tool output

geNomad 1.13.0 and its database 1.9 were not installed on the test machine (they did not fit the disk), so these files
are written by hand in the formats geNomad's source writes (genomad/modules/summary.py: the plasmid and virus summary
headers; find_proviruses.py: provirus names `<contig>|provirus_<start>_<end>`), for the parsers only: one plasmid
call, one provirus and one whole-contig virus, and an empty plasmid summary. Names and numbers are not biology.
