import heapq
import json
import multiprocessing as mp
import multiprocessing.dummy as mpd
import numpy as np
import parasail
import sys

from typing import Iterable, List, Optional, Tuple

from stronger.call.allele import get_n_alleles, call_alleles
from stronger.utils import apply_or_none

__all__ = [
    "call_sample",
]


def log(fd=sys.stderr, level: str = "ERROR"):
    def inner(message: str):
        fd.write(f"[stronger.call] {level}: {message}\n")
        fd.flush()

    return inner


log_error = log(level="ERROR")
log_warning = log(level="WARNING")
log_info = log(level="INFO")
log_debug = log(level="DEBUG")

debug = False

match_score = 2
mismatch_penalty = 7
indel_penalty = 5

dna_matrix = parasail.matrix_create("ACGT", match_score, -1 * mismatch_penalty)


def get_repeat_count(
        start_count: int,
        tr_seq: str,
        flank_left_seq: str,
        flank_right_seq: str,
        motif: str
) -> Tuple[int, int]:
    moving = 0
    to_explore = [(start_count - 1, -1), (start_count + 1, 1), (start_count, 0)]
    sizes_and_scores = {}

    flsub = flank_left_seq
    frsub = flank_right_seq

    db_seq = flank_left_seq + tr_seq + flank_right_seq

    while to_explore:
        size_to_explore, direction = to_explore.pop()
        szs = []

        for i in range(size_to_explore - (1 if moving < 1 else 0), size_to_explore + (2 if moving > -1 else 1)):
            if i < 0:
                continue

            rs = sizes_and_scores.get(i)
            if rs is None:
                mm = motif * i
                r_fwd = parasail.sg_de_stats_rowcol_scan_sat(
                        flsub + mm, db_seq, indel_penalty, indel_penalty, dna_matrix)
                r_rev = parasail.sg_db_stats_rowcol_scan_sat(
                        mm + frsub, db_seq, indel_penalty, indel_penalty, dna_matrix)
                sizes_and_scores[i] = rs = max(r_fwd.score, r_rev.score)

            szs.append((i, rs))

        mv: Tuple[int, int] = max(szs, key=lambda x: x[1])
        if mv[0] > size_to_explore and (new_rc := mv[0] + 1) not in sizes_and_scores:
            to_explore.append((new_rc, 1))
        if mv[0] < size_to_explore and (new_rc := mv[0] - 1) not in sizes_and_scores:
            to_explore.append((new_rc, -1))

    # noinspection PyTypeChecker
    res: Tuple[int, int] = max(sizes_and_scores.items(), key=lambda x: x[1])
    return res


def call_locus(t_idx: int, t: tuple, bf, ref, min_reads: int, min_allele_reads: int, num_bootstrap: int,
               flank_size: int, sex_chroms: Optional[str] = None,
               read_file_has_chr: bool = True, ref_file_has_chr: bool = True) -> Optional[dict]:
    # TODO: Figure out coords properly!!!

    contig: str = t[0]
    read_contig = ("chr" if read_file_has_chr else "") + contig.replace("chr", "")
    ref_contig = ("chr" if ref_file_has_chr else "") + contig.replace("chr", "")

    motif: str = t[-1]
    motif_size = len(motif)

    left_coord = int(t[1])
    right_coord = int(t[2])

    left_flank_coord = left_coord - flank_size - 1
    right_flank_coord = right_coord + flank_size

    ref_left_flank_seq = ""
    ref_right_flank_seq = ""
    ref_seq = ""
    raised = False

    try:
        ref_left_flank_seq = ref.fetch(ref_contig, left_flank_coord, left_coord)
        ref_right_flank_seq = ref.fetch(ref_contig, right_coord - 1, right_flank_coord)
        ref_seq = ref.fetch(ref_contig, left_coord, right_coord - 1)
    except IndexError:
        log_warning(
            f"Coordinates out of range in provided reference FASTA for region {ref_contig} with flank size "
            f"{flank_size}: [{left_flank_coord}, {right_flank_coord}] (skipping locus {t_idx})")
        raised = True
    except ValueError:
        log_error(f"Invalid region '{ref_contig}' for provided reference FASTA (skipping locus {t_idx})")
        raised = True

    if len(ref_left_flank_seq) < flank_size or len(ref_right_flank_seq) < flank_size:
        if not raised:  # flank sequence too small for another reason
            log_warning(f"Reference flank size too small for locus {t_idx} (skipping)")
            return None

    if raised:
        return None

    # Get reference repeat count by our method, so we can calculate offsets from reference
    ref_size = round(len(ref_seq) / motif_size)
    rc = get_repeat_count(ref_size, ref_seq, ref_left_flank_seq, ref_right_flank_seq, motif)

    read_size_dict = {}
    read_weight_dict = {}

    for segment in bf.fetch(read_contig, left_flank_coord, right_flank_coord):
        left_flank_start_idx = -1
        left_flank_end_idx = -1
        right_flank_start_idx = -1
        right_flank_end_idx = -1

        for pair in segment.get_aligned_pairs(matches_only=True):
            # Skip gaps on either side to find mapped flank indices

            if pair[1] <= left_flank_coord:
                left_flank_start_idx = pair[0]
            elif pair[1] < left_coord:
                # Coordinate here is exclusive - we don't want to include a gap between the flanking region and
                # the STR; if we include the left-most base of the STR, we will have a giant flanking region which
                # will include part of the tandem repeat itself.
                left_flank_end_idx = pair[0] + 1  # Add 1 to make it exclusive
            elif pair[1] < right_coord:
                right_flank_start_idx = pair[0]
            elif pair[1] >= right_flank_coord:
                right_flank_end_idx = pair[0]
                break

        if any(v == -1 for v in (
                left_flank_start_idx,
                left_flank_end_idx,
                right_flank_start_idx,
                right_flank_end_idx,
        )):
            if debug:
                log_debug(
                    f"Skipping read {segment.query_name} in locus {t_idx}: could not get sufficient flanking "
                    f"sequence")
            continue

        tr_read_seq = segment.query_sequence[left_flank_end_idx:right_flank_start_idx]

        # Truncate to flank_size (plus some leeway for small indels in flanking region) to stop any expansion sequences
        # from accidentally being included in the flanking region; e.g. if the insert gets mapped onto bases outside
        # the definition coordinates.
        # The +10 here won't include any real TR region if the mapping is solid, since the flank coordinates will
        # contain a correctly-sized sequence.
        flank_left_seq = segment.query_sequence[left_flank_start_idx:left_flank_end_idx][:flank_size+10]
        flank_right_seq = segment.query_sequence[right_flank_start_idx:right_flank_end_idx][-(flank_size+10):]

        read_len = segment.query_alignment_length
        tr_len = len(tr_read_seq)

        read_rc = get_repeat_count(
            start_count=round(tr_len / motif_size),
            tr_seq=tr_read_seq,
            flank_left_seq=flank_left_seq,
            flank_right_seq=flank_right_seq,
            motif=motif,
            # lid=left_coord
        )

        # TODO: Untie weights from actualized read lengths - just pass in tr_flank_len + distribution, then randomly
        #  pull read lengths from distribution which overlaps region for each bootstrap iteration or something?
        #  Can't do that, since boostraps are calculated in advance - calculate mean/stdev of ln(overlapping read)s
        #  and use those as parameter maybe...

        tr_flank_len = tr_len + len(flank_left_seq) + len(flank_right_seq)
        read_size_dict[segment.query_name] = read_rc[0]
        read_weight_dict[segment.query_name] = 1 / ((read_len - tr_flank_len + 1) / (read_len + tr_flank_len - 2))

    n_alleles = get_n_alleles(2, sex_chroms, contig)
    if n_alleles is None:
        return None

    # Dicts are ordered in Python; very nice :)
    read_sizes = np.array(list(read_size_dict.values()))
    read_weights = np.array(list(read_weight_dict.values()))
    read_weights = read_weights / np.sum(read_weights)  # Normalize to probabilities

    call = call_alleles(
        read_sizes, (),
        read_weights, (),
        bootstrap_iterations=num_bootstrap,
        min_reads=min_reads,
        min_allele_reads=min_allele_reads,
        n_alleles=n_alleles,
        separate_strands=False,
        read_bias_corr_min=0,
        gm_filter_factor=3,
        force_int=True,
    )

    return {
        "locus_index": t_idx,
        "contig": contig,
        "start": left_coord,
        "end": right_coord,
        "motif": motif,
        "ref_cn": rc[0],
        "call": apply_or_none(list, call[0]),
        "call_95_cis": apply_or_none(list, call[1]),
        "call_99_cis": apply_or_none(list, call[2]),
        "read_cns": read_size_dict,
        "read_weights": read_weight_dict,
    }


def locus_worker(
        read_file: str,
        reference_file: str,
        min_reads: int,
        min_allele_reads: int,
        num_bootstrap: int,
        flank_size: int,
        sex_chroms: Optional[str],
        locus_queue: mp.Queue) -> List[dict]:

    import pysam as p

    ref = p.FastaFile(reference_file)
    bf = p.AlignmentFile(read_file, reference_filename=reference_file)

    ref_file_has_chr = any(r.startswith("chr") for r in ref.references)
    read_file_has_chr = any(r.startswith("chr") for r in bf.references)

    results: List[dict] = []

    while True:
        td = locus_queue.get()
        sys.stdout.flush()

        if td is None:  # Kill signal
            break

        # print(
        #     "read_file:", read_file,
        #     "reference_file:", reference_file,
        #     "flank_size:", flank_size,
        #     "min_reads:", min_reads,
        #     "min_allele_reads:", min_allele_reads,
        #     "num_bootstrap:", num_bootstrap,
        #     "sex_chroms", sex_chroms,
        # )

        t_idx, t = td
        res = call_locus(
            t_idx, t, bf, ref,
            min_reads=min_reads,
            min_allele_reads=min_allele_reads,
            num_bootstrap=num_bootstrap,
            flank_size=flank_size,
            sex_chroms=sex_chroms,
            read_file_has_chr=read_file_has_chr,
            ref_file_has_chr=ref_file_has_chr,
        )

        if res is not None:
            results.append(res)

    # Sort worker results; we will merge them after
    return sorted(results, key=lambda x: x["locus_index"])


def parse_loci_bed(loci_file: str):
    with open(loci_file, "r") as tf:
        yield from (tuple(line.split("\t")) for line in (s.strip() for s in tf) if line)


def call_sample(
        read_file: str,
        reference_file: str,
        loci_file: str,
        min_reads: int = 4,
        min_allele_reads: int = 2,
        num_bootstrap: int = 100,
        flank_size: int = 70,
        sex_chroms: Optional[str] = None,
        json_path: Optional[str] = None,
        output_tsv: bool = True,
        processes: int = 1):

    manager = mp.Manager()
    locus_queue = manager.Queue()

    job_args = (
        read_file,
        reference_file,
        min_reads,
        min_allele_reads,
        num_bootstrap,
        flank_size,
        sex_chroms,
        locus_queue,
    )
    result_lists = []

    pool_class = mp.Pool if processes > 1 else mpd.Pool
    with pool_class(processes) as p:
        # Spin up the jobs
        jobs = [p.apply_async(locus_worker, job_args) for _ in range(processes)]

        # Add all loci from the BED file to the queue, allowing each job
        # to pull from the queue as it becomes freed up to do so.
        for t_idx, t in enumerate(parse_loci_bed(loci_file), 1):
            locus_queue.put((t_idx, t))

        # At the end of the queue, add a None value (* the # of processes).
        # When a job encounters a None value, it will terminate.
        for _ in range(processes):
            locus_queue.put(None)

        # Gather the process-specific results for combining.
        for j in jobs:
            result_lists.append(j.get())

    # Merge sorted result lists into single sorted list.
    results: Iterable[dict] = heapq.merge(*result_lists, key=lambda x: x["locus_index"])

    if output_tsv:
        for res in results:
            has_call = res["call"] is not None
            sys.stdout.write("\t".join((
                res["contig"],
                str(res["start"]),
                str(res["end"]),
                res["motif"],
                str(res["ref_cn"]),
                ",".join(map(str, sorted(res["read_cns"].values()))),
                "|".join(map(str, res["call"])) if has_call else ".",
                ("|".join("-".join(map(str, res["call_95_cis"]))) if has_call else "."),
            )) + "\n")

    if json_path:
        with open(json_path, "w") as jf:
            json.dump(results, jf)
