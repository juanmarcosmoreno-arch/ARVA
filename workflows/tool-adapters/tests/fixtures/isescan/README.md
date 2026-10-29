# ISEScan fixture — CONSTRUCTED, not tool output

ISEScan 1.7.3 was not installed on the test machine (its environment did not fit the disk next to MOB-suite's
database), so `constructed.tsv` is a file written by hand in the format ISEScan's source writes (pred.py
outputIS4multipleSeqOneFile: the .tsv has the .raw columns), for the parser only: one complete element with a TIR and
one partial element without. Its names (`contig_1`, `IS1181_constructed`) and numbers are not biology.
