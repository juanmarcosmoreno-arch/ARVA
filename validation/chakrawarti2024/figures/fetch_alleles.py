"""Downloads the six MLST alleles compared in Fig. 4 from the PubMLST S. aureus database into <out>/seqs.json."""
import json
import sys
import urllib.request

out = sys.argv[1]
seqs = {}
for name in ("arcC_1", "arcC_3", "arcC_90", "arcC_484", "aroE_35", "aroE_1216"):
    locus, number = name.split("_")
    url = f"https://rest.pubmlst.org/db/pubmlst_saureus_seqdef/loci/{locus}/alleles/{number}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "arva-figures/1.0"}), timeout=60) as r:
        seqs[name] = json.load(r)["sequence"]
with open(f"{out}/seqs.json", "w") as f:
    json.dump(seqs, f, indent=1)
print({k: len(v) for k, v in seqs.items()})
