import pathlib
import pysam

from typing import Optional

__all__ = ["output_vcf"]


VCF_ALLELE_CNV_TR = "<CNV:TR>"

VCF_TR_INFO_RECORDS: tuple[tuple[str, str, str, str], ...] = (
    ("SVLEN", "A", "Integer", "Length of the structural variant"),
    ("CN", "A", "Float", "Copy number of allele"),
    ("RN", "A", "Integer", "Total number of repeat sequences in this allele"),
    ("RUS", ".", "String", "Repeat unit sequence of the corresponding repeat sequence"),
    ("RUL", ".", "Integer", "Repeat unit length of the corresponding repeat sequence"),
    ("RB", ".", "Integer", "Total number of bases in the corresponding repeat sequence"),
    ("CIRUC", ".", "Float", "Confidence interval around RUC"),
    ("CIRB", ".", "Integer", "Confidence interval around RB"),
)


def _build_variant_header(sample_id: str, reference_file: str) -> pysam.VariantHeader:
    vh = pysam.VariantHeader()  # automatically sets VCF version to 4.2

    # Add an absolute path to the reference genome
    vh.add_meta("reference", f"file://{str(pathlib.Path(reference_file).absolute())}")

    # Add all contigs from the reference genome file + lengths
    rf = pysam.FastaFile(reference_file)
    try:
        for contig in rf.references:
            vh.contigs.add(contig, length=rf.get_reference_length(contig))
    finally:
        rf.close()

    # Add CNV:TR alt type (symbolic allele: tandem repeat)
    vh.add_meta("ALT", "<ID=CNV:TR,Description=\"Tandem repeat\">")

    # Set up basic VCF formats
    vh.formats.add("AD", "R", "String", "Read depth for each allele")
    vh.formats.add("DP", 1, "String", "Read depth")
    vh.formats.add("GT", 1, "String", "Genotype")
    vh.formats.add("PS", 1, "String", "Phase set")

    # Add INFO records for tandem repeat copies - these are new to VCF4.4!
    for iv in VCF_TR_INFO_RECORDS:
        vh.info.add(*iv)

    # Add the sample
    vh.add_sample(sample_id)

    return vh


def _vr_pos_key(vr: pysam.VariantRecord) -> int:
    return vr.pos


def output_vcf(
    sample_id: Optional[str],
    reference_file: str,
    results: tuple[dict, ...],
    vcf_path: str,
):
    sample_id_str: str = sample_id or "sample"

    vh = _build_variant_header(sample_id_str, reference_file)
    vf = pysam.VariantFile(vcf_path, "w", header=vh)

    contig_vrs: list[pysam.VariantRecord] = []

    def _write_contig_vrs():
        # sort the variant records by position
        contig_vrs.sort(key=_vr_pos_key)

        # write them to the VCF
        for contig_vr in contig_vrs:
            vf.write(contig_vr)

        # clear the contig variant record list for the new contig
        contig_vrs.clear()

    try:
        last_contig = results[0]["contig"] if results else ""

        for result_idx, result in enumerate(results):
            contig = result["contig"]

            if contig != last_contig:
                # we moved on from the last contig, so write the last batch of variant records to the VCF
                _write_contig_vrs()

            call = result["call"]
            ref_cn = result["ref_cn"]
            alleles = (ref_cn, *sorted(set(c for c in call if c != ref_cn)))

            vr: pysam.VariantRecord = vf.new_record(
                contig=contig,
                # TODO: fix-up coordinates / note positioning
                start=result["start_adj"],
                stop=result["end_adj"],
                alleles=tuple([VCF_ALLELE_CNV_TR] * len(alleles)) if call is not None else (".",),
            )

            # TODO: set up tandem repeat info fields

            vr.samples[sample_id_str]["GT"] = tuple(map(alleles.index, call)) if call is not None else (".",)

            if snvs := result.get("snvs"):  # If we have >= 1 SNV for the STR, set the genotype to be phased
                vr.samples[sample_id_str]["GT"].phased = True
                vr.samples[sample_id_str]["PS"] = result_idx

                for snv in snvs:
                    ref = snv["ref"]
                    snv_alts = tuple(filter(lambda v: v != ref, snv["call"]))
                    snv_gt_lookup = (ref, *snv_alts)

                    snv_vr = vf.new_record(
                        contig=contig,
                        id=snv["id"],
                        # TODO: fix-up coordinates
                        start=snv["pos"],
                        stop=snv["pos"] + 1,
                        ref="G",
                        alts=snv_alts,
                    )

                    # TODO: write "rcs" for sample SNV genotypes - list of #reads per allele

                    snv_vr.samples[sample_id_str]["GT"] = tuple(map(snv_gt_lookup.index, snv["call"]))
                    snv_vr.samples[sample_id_str]["GT"].phased = True
                    snv_vr.samples[sample_id_str]["PS"] = result_idx

                    contig_vrs.append(snv_vr)

            contig_vrs.append(vr)

        _write_contig_vrs()  # write the final contig's worth of variant records to the VCF at the end

    finally:
        vf.close()