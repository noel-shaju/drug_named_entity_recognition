'''
MIT License

Copyright (c) 2023 Fast Data Science Ltd (https://fastdatascience.com)

Maintainer: Thomas Wood

Tutorial at https://fastdatascience.com/drug-named-entity-recognition-python-library/

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

'''

import bz2
import os
import pathlib
import pickle as pkl
from collections import Counter

from drug_named_entity_recognition.structure_file_downloader import download_structures

dbid_to_mol_lookup = {}

this_path = pathlib.Path(__file__).parent.resolve()

# Load dictionary from disk

with bz2.open(this_path.joinpath("drug_ner_dictionary.pkl.bz2"), "rb") as f:
    d = pkl.load(f)

drug_variant_to_canonical = d["drug_variant_to_canonical"]
drug_canonical_to_data = d["drug_canonical_to_data"]
drug_variant_to_variant_data = d["drug_variant_to_variant_data"]

for variant, canonicals in drug_variant_to_canonical.items():
    for canonical in canonicals:
        if canonical in drug_canonical_to_data:
            if "synonyms" not in drug_canonical_to_data[canonical]:
                drug_canonical_to_data[canonical]["synonyms"] = []
            drug_canonical_to_data[canonical]["synonyms"].append(variant)


def get_ngrams(text):
    n = 3
    ngrams = set()
    for i in range(0, len(text) - n + 1, 1):
        ngrams.add(text[i:i + n])
    return ngrams


ngram_to_variant = {}
variant_to_ngrams = {}
for drug_variant in drug_variant_to_canonical:
    ngrams = get_ngrams(drug_variant)
    variant_to_ngrams[drug_variant] = ngrams
    for ngram in ngrams:
        if ngram not in ngram_to_variant:
            ngram_to_variant[ngram] = []
        ngram_to_variant[ngram].append(drug_variant)


def get_fuzzy_match(surface_form: str):
    query_ngrams = get_ngrams(surface_form)
    candidate_to_num_matching_ngrams = Counter()
    for ngram in query_ngrams:
        candidates = ngram_to_variant[ngram]
        for candidate in candidates:
            candidate_to_num_matching_ngrams[candidate] += 1

    candidate_to_jaccard = {}
    for candidate, num_matching_ngrams in candidate_to_num_matching_ngrams.items():
        ngrams_in_query_and_candidate = ngrams.union(variant_to_ngrams[candidate])
        jaccard = num_matching_ngrams / len(ngrams_in_query_and_candidate)
        candidate_to_jaccard[candidate] = jaccard

    if len(candidate_to_num_matching_ngrams) > 0:
        top_candidate = max(candidate_to_jaccard, key=candidate_to_jaccard.get)
        jaccard = candidate_to_jaccard[top_candidate]
        query_ngrams_missing_in_candidate = query_ngrams.difference(variant_to_ngrams[top_candidate])
        candidate_ngrams_missing_in_query = variant_to_ngrams[top_candidate].difference(query_ngrams)
        if max([len(query_ngrams_missing_in_candidate), len(candidate_ngrams_missing_in_query)]) <= 3:
            return top_candidate, jaccard
    return None, None


def find_drugs(tokens: list, is_fuzzy_match=False, is_ignore_case=None, is_include_structure=False):
    """

    @param tokens:
    @param is_fuzzy_match:
    @param is_ignore_case: just for backward compatibility
    @return:
    """

    if is_include_structure:
        if len(dbid_to_mol_lookup) == 0:
            dbid_to_mol_lookup["downloading"] = True
            structures_file = this_path.joinpath("open structures.sdf")
            is_exists = os.path.exists(structures_file)
            if not is_exists:
                download_structures(this_path)

            is_in_structure = True
            current_structure = ""
            with open(structures_file, "r", encoding="utf-8") as f:
                for l in f:
                    if is_in_structure:
                        if "DRUGBANK_ID" not in l:
                            current_structure = current_structure + "\n" + l
                    if l.startswith("DB"):
                        dbid_to_mol_lookup[l.strip()] = current_structure
                        current_structure = ""
                        is_in_structure = False

    drug_matches = []
    is_exclude = set()

    # Search for 2 token sequences
    for token_idx, token in enumerate(tokens[:-1]):
        cand = token + " " + tokens[token_idx + 1]
        cand_norm = cand.lower()

        match = drug_variant_to_canonical.get(cand_norm, None)

        if match:

            for m in match:
                match_data = dict(drug_canonical_to_data[m]) | drug_variant_to_variant_data.get(cand_norm, {})

                drug_matches.append((match_data, token_idx, token_idx + 1))
                is_exclude.add(token_idx)
                is_exclude.add(token_idx + 1)
        elif is_fuzzy_match:
            fuzzy_matched_variant, similarity = get_fuzzy_match(cand_norm)
            if fuzzy_matched_variant is not None:
                match = drug_variant_to_canonical[fuzzy_matched_variant]
                for m in match:
                    match_data = dict(drug_canonical_to_data[m]) | drug_variant_to_variant_data.get(
                        fuzzy_matched_variant, {})
                    match_data["match_type"] = "fuzzy"
                    match_data["match_similarity"] = similarity

                    drug_matches.append((match_data, token_idx, token_idx + 1))

    for token_idx, token in enumerate(tokens):
        if token_idx in is_exclude:
            continue
        cand_norm = token.lower()
        match = drug_variant_to_canonical.get(cand_norm, None)
        if match:
            for m in match:
                match_data = dict(drug_canonical_to_data[m]) | drug_variant_to_variant_data.get(cand_norm, {})
                drug_matches.append((match_data, token_idx, token_idx))
        elif is_fuzzy_match:
            fuzzy_matched_variant, similarity = get_fuzzy_match(cand_norm)
            if fuzzy_matched_variant is not None:
                match = drug_variant_to_canonical[fuzzy_matched_variant]
                for m in match:
                    match_data = dict(drug_canonical_to_data[m]) | drug_variant_to_variant_data.get(
                        fuzzy_matched_variant, {})
                    match_data["match_type"] = "fuzzy"
                    match_data["match_similarity"] = similarity
                    drug_matches.append((match_data, token_idx, token_idx + 1))

    if is_include_structure:
        for match in drug_matches:
            match_data = match[0]
            if "drugbank_id" in match_data:
                structure = dbid_to_mol_lookup.get(match_data["drugbank_id"])
                if structure is not None:
                    match_data["structure_mol"] = structure

    return drug_matches
