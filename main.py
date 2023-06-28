import numpy as np
from pathlib import PosixPath
from Bio.PDB import PDBParser


class Protein:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', '') 
        self.dtype = kwargs.get('name', '')
        self.sequence = kwargs.get('sequence', '')
        self.coord = np.array(kwargs.get('coord', []), dtype=float)
        self.max_bfactor = kwargs.get('max_bfactor', 0.0)
        self.min_plddt = kwargs.get('min_plddt', 0.0)
        self.idx = np.array(kwargs.get('idx', []), dtype=int)
        self.plddt = np.array(kwargs.get('plddt', []), dtype=float)
        self.bfactor = np.array(kwargs.get('bfactor', []), dtype=float)
        self.path = PosixPath(kwargs.get('path', ''))
        self.neigh_idx = []
        self.neigh_tensor = []
        self.neigh_cut = kwargs.get('neigh_cut', 0.0)

    

    def load_data_from_path(self, path):
        data = _read_alpha_carbon(path)
        # [xyz, idx, seq, bfac]
        self.coord = data[0]
        self.idx = data[1]
        self.sequence = data[2]
        self.bfactor = data[3]
        self.max_bfactor = np.max(self.bfactor)
        self.min_plddt = np.min(self.plddt)
    
    
    def load_coordinates(self, coordinates):
        self.coord = coordinates
    

    def get_local_neighborhood(self):
        xyz = self.coord
        dist = cdist(xyz, xyz)
        # I added dtype property, code is from get_local_structure in average_structure.py
        if self.dtype in ['af', 'dmp']:            
            plddt = self.plddt

            # Get the indices of neighbours
            # If plddt[j] (neighbour) is less than min_conf, then don't include that index
            # If plddt[i] is less than min_conf, then don't calculate anything
            idx_list = [np.where((d > 0) & (d <= cut) & (plddt >= min_conf) & (p >= min_conf))[0] for d, p in zip(dist, plddt)]
        elif self.dtype == 'pdb':
            # In the case of PDB data, disordered residues will show up as NAN,
            # so we ignore these
            idx_list = [np.where((d > 0) & (d <= cut) & (np.isfinite(d)))[0] for d in dist]


        self.neigh_idx = idx_list
        self.neigh_tensor = self._get_ldt()

    # From average_struct.py:
    def _get_ldt():  
        l, dim = self.coord.shape
        # There is probabily a faster way of doing this!
        dist = np.zeros((l, l, dim), float)
        # if idx is not provided, then run through
        # all positions -1 < i < j < l
        if isinstance(self.neigh_idx, str):
            for i in range(l - 1):
                for j in range(i + 1, l):
                    d = self.coord[i] - self.coord[j]
                    dist[i,j] = d
                    dist[j,i] = - d
        else:
            # If the neighbourhood is provided (idx),
            # then only calculate distance vectors between
            # neighbouring alpha carbons
            for i in range(l):
                for j in self.neigh_idx[i]:
                    dist[i,j] = self.coord[i] - self.coord[j]
        return dist
    
    # From pdb_parser.py: 
    def _read_alpha_carbon(path, chain='', model=0, all_atom=False):
        parser = PDBParser(QUIET=True)
        chains = list(parser.get_structure('', path)[model])
        xyz, idx, seq, bfac = [], [], [], []

        for ch in chains:
            if ch.get_id() == chain or chain == '':
                for residue in ch:
                    try:
                        h, i, _ = residue.get_id()
                        # Ignore HETATM entries
                        if h.strip() != '':
                            continue
                        aa = residue.resname
                        if all_atom:
                            for atom in residue:
                                xyz.append(atom.coord)
                                idx.append(i)
                                seq.append(parse_3letter(aa))
                                bfac.append(atom.bfactor)
                        else:
                            if 'CA' not in residue:
                                continue
                            ca = residue['CA'].coord
                            xyz.append(ca)
                            idx.append(i)
                            seq.append(parse_3letter(aa))
                            bfac.append(residue['CA'].bfactor)
                    except Exception as e:
                        print(f"{path}\n{e}")
                        continue
        return [np.array(x) for x in [xyz, idx, seq, bfac]]



class AverageProtein:
    def __init__(self, proteins, **kwargs):
        self.proteins = proteins    
        self.dtype = proteins[0].dtype
        self.idx = np.array(kwargs.get('idx', []), dtype=int)
        self.plddt = np.array(kwargs.get('plddt', []), dtype=float)
        self.bfactor = np.array(kwargs.get('bfactor', []), dtype=float)
        self.name = kwargs.get('name', '')
        self.neigh_idx = []
        self.neigh_tensor = []
        self.neigh_cut = kwargs.get('neigh_cut', 0.0)
        self.max_bfactor = kwargs.get('max_bfactor', 0.0)
        self.min_plddt = kwargs.get('min_plddt', 0.0)
    
    def get_average_local_neighborhood(self):
        # adapted from average_local_structure in average_structure.py 
        L = self.proteins[0].coord.shape[0]
        if self.dtype in ['af', 'dmp']:
            xyz_list = [protein.coord for protein in self.proteins]
        elif self.dtype == 'pdb':
            coord_list = [protein.coord for protein in self.proteins]

        # Get the average distance matrix
        ca_dist = np.mean([cdist(x, x) for x in coord_list], axis=0)

        if self.dtype in ['af', 'dmp']:
            # Get the average pLDDT values
            plddt = np.mean([protein.plddt for protein in self.proteins.coord], axis=0)

            # Get the indices of neighbours
            # If plddt[j] (neighbour) is less than min_conf, then don't include that index
            # If plddt[i] is less than min_conf, then don't calculate anything
            idx_list = [np.where((d > 0) & (d <= cut) & (plddt >= min_conf) & (p >= min_conf))[0] for d, p in zip(ca_dist, plddt)]
        elif self.dtype == 'pdb':
            # In the case of PDB data, disordered residues will show up as NAN
            idx_list = [np.where((d > 0) & (d <= cut) & (np.isfinite(d)))[0] for d in ca_dist]

        self.neigh_idx = idx_list
        # Get the local distance tensors for each structure
        ldt = np.array([self._get_ldt(coord) for coord in coord_list])

        # Rotate local distance tensors,
        # and arrange by residue
        ldt_list = _rotate_all_ldt(ldt, idx_list)

        # Get the average local distance tensor
        ave_ldt = _average_all_ldt(ldt_list, idx_list)

        self.neigh_tensor = ave_ldt
    
    ### "P" is the set of points to be mapped to "Q"
    def _rotate_points(P, Q):
        H = P.T @ Q
        U, S, Vt = np.linalg.svd(H)
        V = Vt.T
        D = np.linalg.det(V @ U.T)
        E = np.array([[1, 0, 0], [0, 1, 0], [0, 0, D]])
        R = V @ E @ U.T
        Pnew = np.array([R @ p for p in P])
        return Pnew


    def _get_ldt(self, coord):
        l, dim = coord.shape()
        # There is probabily a faster way of doing this!
        dist = np.zeros((l, l, dim), float)
        # if idx is not provided, then run through
        # all positions -1 < i < j < l
        if isinstance(self.neigh_idx, str):
            for i in range(l - 1):
                for j in range(i + 1, l):
                    d = coord[i] -coord[j]
                    dist[i,j] = d
                    dist[j,i] = - d
        else:
            # If the neighbourhood is provided (idx),
            # then only calculate distance vectors between
            # neighbouring alpha carbons
            for i in range(l):
                for j in self.neigh_idx[i]:
                    dist[i,j] = coord[i] - coord[j]
        return dist

    ### For each residue j, rotate all neighbourhoods to match the first one
    def _rotate_all_ldt(ldt, idx_list):
        L = ldt.shape[1]
        ldt_list = [None] * L
        for i in range(len(ldt)):
            for j in range(L):
                if not i:
                    # Do not rotate the first example for residue j
                    # Initialize the list
                    ldt_list[j] = [ldt[i][j,idx_list[j]]]
                else:
                    # Rotate everything else so that it matches the first example
                    rotated_ldt = rotate_points(ldt[i][j,idx_list[j]], ldt_list[j][0])
                    ldt_list[j].append(rotated_ldt)
        return ldt_list

    def _average_all_ldt(ldt_list, idx_list):
        L = len(ldt_list)
        ave_ldt = [None] * L
        for i in range(L):
            if (len(idx_list[i]) > 1):
                ave_ldt[i] = np.mean(ldt_list[i], axis=0)
            else:
                ave_ldt[i] = []
        return ave_ldt



class Deformation:
    def __init__(self, protein_1, protein_2, method, **kwargs):
        if isinstance(protein_1, str) or isinstance(protein_1, PosixPath) or isinstance(protein_1, list):
            self.prot1 = Protein()
            self.prot1.load_data_from_path(protein_1)
        else:
            self.prot1 = protein_1
        
        if isinstance(protein_2, str) or isinstance(protein_2, PosixPath) or isinstance(protein_2, list):
            self.prot2 = Protein()
            self.prot2.load_data_from_path(protein_2)
        else:
            self.prot2 = protein_2
        
        self.method = method
        self.neigh_cut = kwargs.get('neigh_cut', 0.0)
        self.max_bfactor = kwargs.get('max_bfactor', 0.0)
        self.min_plddt = kwargs.get('min_plddt', 0.0)
        self.deformation = {}
        self.mutations = []
        self.mutation_idx = []
    
    def compare_sequences(self):
        return np.where(np.array(list(s1)) != np.array(list(s2)))[0]
    
    def calculate_deformation(self):
        # Calculate deformation based on the specified method
        self.deformation = {}
        if self.method == 'all':
            self.calculate_deformation_all()
        elif self.method == 'lddt':
            self.deformation['lddt'] = self.calculate_deformation_lddt()
        elif self.method == 'ldd':
            self.deformation['ldd'] = self.calculate_deformation_ldd()
        elif self.method == 'ntd':
            self.deformation['ntd'] = self.calculate_deformation_ntd()
        elif self.method == 'shear':
            self.deformation['shear'] = self.calculate_deformation_shear()
        elif self.method == 'strain':
            self.deformation['strain'] = self.calculate_deformation_strain()


    def calc_dist_from_mutation(c1, c2, sub_pos):
        # If none differ, then return np.nan
        if not len(sub_pos):
                #       print("Sequences are identical")
            return np.zeros(len(c1)) * np.nan
        
        # Calculate mindist using the full array (inc. nan)
        dc1 = cdist(c1, c1[sub_pos])
        dc2 = cdist(c2, c2[sub_pos])

        # Average the distance across both structures,
        # and get the minimum distance per residue to a mutated position
        mindist = np.nanmin(0.5 * (dc1 + dc1), axis=1)

        return mindist


    def calculate_deformation_all(self):
        self.deformation['lddt'] = self.calculate_deformation_lddt()
        self.deformation['ldd'] = self.calculate_deformation_ldd()
        self.deformation['ntd'] = self.calculate_deformation_ntd()
        self.deformation['shear'] = self.calculate_deformation_shear()
        self.deformation['strain'] = self.calculate_deformation_strain()


    def calculate_deformation_lddt(bins=[]):
        lddt = []

        # If no bins are provided, use the standard set
        if not len(bins):
            bins = [0.5, 1, 2, 4]

        for i in range(len(self.prot1.neigh_tensor)):
            # If no data for residue, return np.nan
            if (not len(self.prot1.neigh_tensor[i])) | (not len(self.prot2.neigh_tensor[i])):
                lddt.append(np.nan)
                continue

            # Get shared indices
            i1 = [j for j, k in enumerate(self.prot1.neigh_idx[i]) if k in self.prot2.neigh_idx[i]]
            i2 = [j for j, k in enumerate(self.prot2.neigh_idx[i]) if k in self.prot1.neigh_idx[i]]
            # If no shared indices, return np.nan
            if not len(i1):
                lddt.append(np.nan)
                continue

            # Get neighbourhood tensors
            c1 = self.prot1.neigh_tensor[i][i1]
            c2 = self.prot2.neigh_tensor[i][i2]

            # Get local distance vectors
            v1 = np.linalg.norm(c1, axis=1)
            v2 = np.linalg.norm(c2, axis=1)

            # Get local distance difference vector
            dv = v2 - v1

            lddt.append(np.sum([np.sum(dv<=cut) for cut in bins]) / (4 * len(dv)))

        return np.array(lddt)


    def calculate_deformation_ldd(self):
        ldd = []
        for i in range(len(self.prot1.neigh_tensor)):
            # If no data for residue, return np.nan
            if (not len(self.prot1.neigh_tensor[i])) | (not len(self.prot2.neigh_tensor[i])):
                ldd.append(np.nan)
                continue

            # Get shared indices
            i1 = [j for j, k in enumerate(self.prot1.neigh_idx[i]) if k in self.prot2.neigh_idx[i]]
            i2 = [j for j, k in enumerate(self.prot2.neigh_idx[i]) if k in self.prot1.neigh_idx[i]]
            # If no shared indices, return np.nan
            if not len(i1):
                ldd.append(np.nan)
                continue

            # Calculate local distance vectors
            ld1 = np.array([np.linalg.norm(l) for l in self.prot1.neigh_tensor[i][i1]])
            ld2 = np.array([np.linalg.norm(l) for l in self.prot2.neigh_tensor[i][i2]])

            # Calculate local distance difference 
            if norm:
                ldd.append(np.linalg.norm(ld1 - ld2) / len(i1))
            else:
                ldd.append(np.linalg.norm(ld1 - ld2))

        return np.array(ldd)


    def calculate_deformation_ntd():
        ntd = []
        for i in range(len(self.prot1.neigh_tensor)):
            # If no data for residue, return np.nan
            if (not len(self.prot1.neigh_tensor[i])) | (not len(self.prot2.neigh_tensor[i])):
                ntd.append(np.nan)
                continue

            # Get shared indices
            i1 = [j for j, k in enumerate(self.prot1.neigh_idx[i]) if k in self.prot2.neigh_idx[i]]
            i2 = [j for j, k in enumerate(self.prot2.neigh_idx[i]) if k in self.prot1.neigh_idx[i]]
            # If no shared indices, return np.nan
            if not len(i1):
                ntd.append(np.nan)
                continue

            # Get neighbourhood tensors
            c1 = self.prot1.neigh_tensor[i][i1]
            c2 = self.prot2.neigh_tensor[i][i2]

            # Rotate neighbourhood tensor and calculate Euclidean distance
            if norm:
                ntd.append(np.linalg.norm(AS.rotate_points(c2, c1) - c1) / len(i1))
            else:
                ntd.append(np.linalg.norm(AS.rotate_points(c2, c1) - c1))

        return np.array(ntd)


    def calculate_deformation_shear():
        shear = []
        for i in range(len(self.prot1.neigh_tensor)):
            # If no data for residue, return np.nan
            if (not len(self.prot1.neigh_tensor[i])) | (not len(self.prot2.neigh_tensor[i])):
                shear.append(np.nan)
                continue

            # Get shared indices
            i1 = [j for j, k in enumerate(self.prot1.neigh_idx[i]) if k in self.prot2.neigh_idx[i]]
            i2 = [j for j, k in enumerate(self.prot2.neigh_idx[i]) if k in self.prot1.neigh_idx[i]]
            # If no shared indices, return np.nan
            if not len(i1):
                shear.append(np.nan)
                continue

            # Get neighbourhood tensors
            u1 = self.prot1.neigh_tensor[i][i1]
            u2 = self.prot2.neigh_tensor[i][i2]
            try:
                duu = u2 @ u2.T - u1 @ u1.T
                uu = np.linalg.inv(u1.T @ u1) 
                C = 0.5 * (uu @ u1.T @ duu @ u1 @ uu)
                shear.append(0.5 * np.sum(np.diag(C@C) - np.diag(C)**2))
            except Exception as e:
                shear.append(np.nan)

        return np.array(shear)


    def calculate_deformation_strain():
        strain = []
        for i in range(len(self.prot1.neigh_tensor)):
            # If no data for residue, return np.nan
            if (not len(self.prot1.neigh_tensor[i])) | (not len(self.prot2.neigh_tensor[i])):
                strain.append(np.nan)
                continue

            # Get shared indices
            i1 = [j for j, k in enumerate(self.prot1.neigh_idx[i]) if k in self.prot2.neigh_idx[i]]
            i2 = [j for j, k in enumerate(self.prot2.neigh_idx[i]) if k in self.prot1.neigh_idx[i]]
            # If no shared indices, return np.nan
            if not len(i1):
                strain.append(np.nan)
                continue

            # Get neighbourhood tensors
            c1 = self.prot1.neigh_tensor[i][i1]
            c2 = self.prot2.neigh_tensor[i][i2]

            # Rotate neighbourhood tensor and calculate Euclidean distance
            c3 = AS.rotate_points(c2, c1)
            s = 0.0
            for j in range(len(c1)):
                s += np.linalg.norm(c3[j] - c1[j]) / np.linalg.norm(c1[j])

            if norm:
                s /= len(i1)

            strain.append(s)

        return np.array(strain)

