import numpy as np
from Bio import Seq, SeqIO, SeqRecord, pairwise2
from Bio.PDB import PDBParser, MMCIF2Dict


#############################################################
### Load coordinates from file


### Read 3-letter code in title case
def parse_3letter(x):
    return IUPACData.protein_letters_3to1.get(x[0].upper() + x[1:].lower(), 'X')


### Load data corresponding to rows starting with ATOM
###     (coordinates, residue index, sequence,  
def parse_pdb_coordinates(path, chain='', model=0, all_atom=False):
    parser = PDBParser(QUIET=True)
    chains = list(parser.get_structure('', path)[model])
    coord, idx, seq, bfac = [], [], [], []

    for ch in chains:
        if (ch.get_id() == chain) or (chain == ''):
            for residue in ch:
                try:
                    h, i, _ = residue.get_id()
                    # Ignore HETATM entries
                    if h.strip() != '':
                        continue
                    aa = residue.resname
                    if all_atom:
                        for atom in residue:
                            coord.append(atom.coord)
                            idx.append(i)
                            seq.append(parse_3letter(aa))
                            bfac.append(atom.bfactor)
                    else:
                        if 'CA' not in residue:
                            continue
                        ca = residue['CA'].coord
                        coord.append(ca)
                        idx.append(i)
                        seq.append(parse_3letter(aa))
                        bfac.append(residue['CA'].bfactor)
                except Exception as e:
                    print(f"{path}\n{e}")
                    continue
    return [np.array(x) for x in [coord, idx, seq, bfac]]



#############################################################
### Load SEQRES

def load_pdb_seqres(pdb_id, chain=''):
    for record in SeqIO.parse(PATH_PDB.joinpath(pdb_id[1:3], f"pdb{pdb_id}.ent"), "pdb-seqres"):
        if record.annotations['chain'] == chain:
            return str(record.seq)


#############################################################
### Load PDB file, reorder indices so they start from zero,
### and fill in missing coordinates / Bfactor with NaN values.


### Load SEQRES sequence, and use that to get a more complete
### description of the protein structure that preserves residues
### that are missing atoms.
### Doesn't work for some rare weird cases that you get in the PDB:
###     e.g. microheterogeneity??? (multiple amino acids for one site, somehow; eg. 1eis)
def load_and_fix_pdb_data(path, chain='', model=0):
    # Load the sequence from the SEQRES part
    seqres = PP.load_pdb_seqres(pdb_id, chain)

    # Load the coords, sequence, etc., from the ATOM part
    xyz, idx, seq, bfac = read_alpha_carbon_pdb(pdb_id, chain, model=model)

    # If the ATOM sequence is longer than the SEQRES sequence,
    # then there is a problem
    if len(seqres) < len(seq):
        print("Preposterous! Where have the extra residues come from???")
        print(pdb_id, chain, len(seqres), len(seq))

    # If there are no missing atoms, the two sequences will be equal.
    # In this case, the indices will be an integer series starting at 0
    if seqres == ''.join(seq):
        idx = np.arange(len(seq))
    else:
        # If there are missing atoms, try to align the SEQRES / ATOM sequences
        # to get the correct indices
        is_clear, idx = match_xyz_indices_to_seqres(seqres, xyz, seq)
        # If not "is_clear" (if any atom positions are ambiguous),
        # ignore ambiguous atoms
        if not is_clear:
            if len(idx):
                xyz, seq, bfac = [x[idx] for x in [xyz, seq, bfac]]
            else:
                raise Exception(f"Error reading pdb file\n\t{path}")

    # Fill in missing coordinates with nan values
    xyz_nan = np.zeros((len(seqres), 3), float) * np.nan
    xyz_nan[idx] = xyz 

    pickle.dump([xyz, idx, seq, bfac, xyz_nan], open(path_out, 'wb'))
    return [np.array(x) for x in [xyz, idx, seq, bfac, xyz_nan]]


### Match SEQRES sequence to the sequence obtained from 
### the atomic coordinates. Do NOT allow any mismatches, only gaps.
def match_xyz_indices_to_seqres(seqres, xyz, seq):
    # Find all residues that are connected along the backbone,
    # and cluster them into unbroken stretches of amino acids
    seq_clusters = find_neighbours(seq, xyz)
    # Run a strict alignment algorithm that discards candidate alignments
    # if they do not agree provide the same set of unbroken sequences
    # of amino acids (sequence clusters)
    candidates = align_sequences(seqres, ''.join(seq), seq_clusters)
    if len(candidates) > 1:
        # If there is more than one alignment, return a single index
        # that corresponds to the positions in the first alignment.
        return False, resolve_ambiguity(candidates)

    elif len(candidates) == 1:
        # If there is only one candidate...
        return True, np.where(np.array(list(candidates[0])) != '-')[0]

    else:
        # If there are no candidates identified with the strict alignment algorithm,
        # run without enforcing equivalence of sequence clusters
        candidates = align_sequences(seqres, ''.join(seq))
        if len(candidates) > 1:
            return False, resolve_ambiguity(candidates)

        elif len(candidates) == 1:
            return True, np.where(np.array(list(candidates[0])) != '-')[0]

        else:
            # If there are still no candidates, return False
            return False, []


### Distance between alpha-carbons in neighbouring
### amino acids ought to be about 3.8 AA.
### Cutoff is higher than this, due to inaccuracies in the PDB.
### See "12ca", positions 125-127 as an example
### Occasionally, this method fails because a string of disordered residues
### are missing, yet the amino acids bookending the missing residues are indexed beside
### each other; not actually that rare (e.g., 4s34_A)
def find_neighbours(seq, xyz, cut=4.3):
    D = np.linalg.norm(xyz[:-1] - xyz[1:], axis=1)
    seq_clusters = []
    cluster = seq[0]
    for s, d in zip(seq[1:], D):
        if d < cut:
            cluster = cluster + s
        else:
            seq_clusters.append(cluster)
            cluster = s
    seq_clusters.append(cluster)
    return seq_clusters


def align_sequences(seqres, seq, seq_clusters=''):
    # Set mismatch penalty to negative infinity,
    # since no mismatches are not allowed
    ni = -np.inf
    candidates = []
    # Convert sequence clusters to set
    if not isinstance(seq_clusters, str):
        seqA = set(seq_clusters)

    # Loop through candidate alignments
    for align in pairwise2.align.globalmd(seqres, seq, 0, ni, ni, ni, -1, -0.5):
        s1, s2 = align[:2]
        # If sequence clusters are provided, only allow candidates that
        # include all sequence clusters as unbroken sequences
        if not isinstance(seq_clusters, str):
            # Break alignment into sequence clusters by splitting
            # at gaps
            clusters = [c for c in s2.split('-') if len(c)]
            # If all of the previously identified sequence clusters
            # are found in the alignment, add the candidate to the output
            if seqA.issubset(set(clusters)):
                candidates.append(s2)
        else:
            candidates.append(s2)
    return candidates


### Discard any ambiguous residues.
# If there are ambiguous regions, they will be
# as long as the number of candidates, so we can
# account for the indices
# These cases are rare: the algorithm is only called for 3 PDB entries out of ~4000.
def resolve_ambiguity(cand):
    cand = np.array([list(x) for x in cand])
    N = len(cand)
    idx = []
    icount = -1
    # Loop through sequence positions (including gaps)
    for i in range(cand.shape[1]):
        # If no gaps, there is no ambiguity; count the index
        if '-' not in cand[:,i]:
            icount += 1
            idx.append(icount)
        # If there are gaps, ignore the index if there is a gap
        # in the first candidate alignment
        else:
            if cand[0,i] != '-':
                icount += 1
#               idx.append(icount)
    return np.array(idx)




