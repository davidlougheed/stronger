# Advanced caller usage and configuration


## All optional flags

* `--min-reads ##`: Minimum number of supporting reads needed to make a call. **Default:** 4
* `--min-allele-reads ##`: Minimum number of supporting reads needed to call a specific allele size. 
  **Default:** 2
* `--min-avg-phred ##`: Minimum average PHRED score for relevant bases (flanking region + tandem repeat).
  Read segments with average PHRED scores below this (common with a threshold of ~13 and ONT Ultra Long reads, 
  for example) will be skipped. **Default:** 13
* `--flank-size ##`: Size of the flanking region to use on either side of a region to properly anchor reads. 
  **Default:** 70
* `--targeted` or `-t`: Turn on targeted genotyping mode, which re-weights longer reads differently. Use this option if
  the alignment file contains targeted reads, e.g. from PacBio No-Amp Targeted Sequencing. **Default:** off
* `--fractional` or `f`: Turn on fractional genotyping mode, which allows for partial copy numbers in the reference and 
  in allele calls. *Experimental!* **Default:** off
* `--num-bootstrap ###` or `-b`: Now many bootstrap re-samplings to perform. **Default:** 100
* `--sex-chr ??` or `-x`: Sex chromosome configuration. **Without this, loci in sex chromosomes will not be genotyped.**
  Can be any configuration of Xs and Ys; only count matters. **Default:** *none*
* `--json [path]` or `-j`: Path to output JSON call data to. JSON call data is more detailed than the `stdout` TSV 
  output. **Default:** *none*
* `--no-tsv`: Suppresses TSV output to `stdout`. Without `--json`, no output will be generated, which isn't very 
  helpful. **Default:** TSV output on
* `--seed`: Seed the random number generator used for all random sampling, Gaussian mixture modeling, etc. 
  Useful for replicability.


## Usage on HPC machines

We have tested STRkit on three different clusters associated with the 
Digital Research Alliance of Canada (formerly Compute Canada). 

Usage is pretty straightforward; for our use cases we set up a Python virtual environment
with the `strkit` package installed, and ran a SLURM batch job which looks something like:

```bash
#!/bin/bash
#SBATCH --mem=16G
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --time=1-00
#SBATCH --account=rrg-xxxxx


module load python/3.8

cd /home/xxxxx || exit
source env/bin/activate

export OMP_NUM_THREADS=1  # Legacy, should be automatic now but drastically improved performance
strkit call \
  --loci /path/to/catalog \
  --ref /path/to/ref.fa.gz \
  --processes 10 \
  --seed 342 \
  path/to/sample.bam

deactivate

```