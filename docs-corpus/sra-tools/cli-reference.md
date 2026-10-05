Usage:
  prefetch [options] <SRA accession> [...]
  Download SRA files and their dependencies

  prefetch [options] --perm <JWT cart file> <SRA accession> [...]
  Download SRA files and their dependencies from JWT cart

  prefetch [options] --cart <kart file>
  Download cart file

  prefetch [options] <URL> --output-file <FILE>
  Download URL to FILE

  prefetch [options] <URL> [...] --output-directory <DIRECTORY>
  Download URL or URL-s to DIRECTORY

  prefetch [options] <SRA file> [...]
  Check SRA file for missed dependencies and download them


Options:
  -T|--type <value>                Specify file type to download. Default: sra 
  -t|--transport <http|fasp|both>  Transport: one of: fasp; http; both 
                                   [default]. (fasp only; http only; first try 
                                   fasp (ascp), use http if cannot download 
                                   using fasp). 
  --location <value>               Location of data. 

  -N|--min-size <size>             Minimum file size to download in KB 
                                   (inclusive). 
  -X|--max-size <size>             Maximum file size to download in KB 
                                   (exclusive). Default: 20G 
  -f|--force <yes|no|all|ALL>      Force object download: one of: no, yes, 
                                   all, ALL. no [default]: skip download if the 
                                   object if found and complete; yes: download 
                                   it even if it is found and is complete; all: 
                                   ignore lock files (stale locks or it is 
                                   being downloaded by another process use 
                                   at your own risk!); ALL: ignore lock files, 
                                   restart download from beginning. 
  -r|--resume <yes|no>             Resume partial downloads: one of: no, yes 
                                   [default]. 
  -C|--verify <yes|no>             Verify after download: one of: no, yes 
                                   [default]. 
  -p|--progress                    Show progress. 
  -H|--heartbeat <value>           Time period in minutes to display download 
                                   progress. (0: no progress), default: 1 

  --eliminate-quals                Download SRA Lite files with simplified 
                                   base quality scores, or fail if not 
# fasterq-dump (sra-tools)

Usage:
  fasterq-dump <path> [options]
  fasterq-dump <accession> [options]

Options:
  -F|--format                      format (special, fastq, default=fastq) 
  -o|--outfile                     output-file 
  -O|--outdir                      output-dir 
  -b|--bufsize                     size of file-buffer dflt=1MB 
  -c|--curcache                    size of cursor-cache dflt=10MB 
  -m|--mem                         memory limit for sorting dflt=100MB 
  -t|--temp                        where to put temp. files dflt=curr dir 
  -e|--threads                     how many thread dflt=6 
  -p|--progress                    show progress 
  -x|--details                     print details 
  -s|--split-spot                  split spots into reads 
  -S|--split-files                 write reads into different files 
  -3|--split-3                     writes single reads in special file 
  --concatenate-reads              writes whole spots into one file 
  -Z|--stdout                      print output to stdout 
  -f|--force                       force to overwrite existing file(s) 
  --skip-technical                 skip technical reads 
  --include-technical              include technical reads 
  -M|--min-read-len                filter by sequence-len 
  --table                          which seq-table to use in case of pacbio 
  -B|--bases                       filter by bases 
  -A|--append                      append to output-file 
  --fasta                          produce FASTA output 
  --fasta-unsorted                 produce FASTA output, unsorted 
  --fasta-ref-tbl                  produce FASTA output from REFERENCE tbl 
  --fasta-concat-all               concatenate all rows and produce FASTA 
  --internal-ref                   extract only internal REFERENCEs 
  --external-ref                   extract only external REFERENCEs 
  --ref-name                       extract only these REFERENCEs 
  --ref-report                     enumerate references 
  --use-name                       print name instead of seq-id 
  --seq-defline                    custom defline for sequence:  $ac=accession, 
                                   $sn=spot-name,  $sg=spot-group, $si=spot-id,  
                                   $ri=read-id, $rl=read-length 
  --qual-defline                   custom defline for qualities:  same as 
                                   seq-defline 
  -U|--only-unaligned              process only unaligned reads 
  -a|--only-aligned                process only aligned reads 
  --disk-limit                     explicitly set disk-limit 
  --disk-limit-tmp                 explicitly set disk-limit for temp. files 
  --size-check                     switch to control: on=perform size-check 
                                   (default),  off=do not perform size-check,  
                                   only=perform size-check only 
  --ngc <PATH>                     PATH to ngc file 

  -h|--help                        Output brief explanation for the program. 
  -V|--version                     Display the version of the program then 
                                   quit. 
  -L|--log-level <level>           Logging level as number or enum string. One 
                                   of (fatal|sys|int|err|warn|info|debug) or 
                                   (0-6) Current/default is warn. 
  -v|--verbose                     Increase the verbosity of the program 
                                   status messages. Use multiple times for more 
                                   verbosity. Negates quiet. 
