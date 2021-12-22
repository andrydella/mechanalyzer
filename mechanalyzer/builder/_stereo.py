"""
  Code to expand the mechanism using stereochemistry

    maybe remove all inchis that are not incomplete?
"""

import os
import copy
import automol
from autorun import execute_function_in_parallel
import mechanalyzer.parser
from mechanalyzer.builder._update import update_spc_dct_from_reactions
from mechanalyzer.builder._update import update_rxn_dct
from mechanalyzer.builder._update import rxn_name_str
from chemkin_io.writer._util import format_rxn_name


# MAIN CALLABLE
# def expand_mech_stereo(mech_rxn_dct, mech_spc_dct, nprocs='auto'):
def expand_mech_stereo(inp_mech_rxn_dct, inp_mech_spc_dct, nprocs=1):
    """ Build list of stereochemistry to reactions

        Currently, we assume that the species in them mech_spc_dct have
        stereochemistry already added to them.
    """

    def _expand(name_ich_dct, rxns, output_queue):
        """ Expand reactons
        """
        srxns = ()
        for rxn in rxns:

            log1 = f'\nExpanding Stereo for Reaction: {format_rxn_name(rxn)}\n'

            # Reformat reaction to use InChI instead of mechanism name
            # Split thrdbdy off, not needed for stereo code, add back later
            rxn_ich = _rxn_name_to_ich(rxn, name_ich_dct)
            _rxn_ich = (rxn_ich[0], rxn_ich[1])
            thrdbdy = rxn_ich[2]

            # Build list of all stereochemically allowed versions of reaction
            ste_rxns_lst, log2 = _ste_rxn_lsts(_rxn_ich)

            # Filter redundant reactions from each enantiomer pairs
            ste_rxns_lst, removed_rxns_lst = _remove_enantiomer_reactions(
                ste_rxns_lst)

            # Appropriately format the reactions with third body
            ste_rxns_lst = _add_third(ste_rxns_lst, thrdbdy)
            removed_rxns_lst = _add_third(removed_rxns_lst, thrdbdy)

            # Print final list of stereochemical reactions to potentially add
            log3 = _stereo_results(rxn, ste_rxns_lst, removed_rxns_lst)

            # Add to overall stereo reactions list
            srxns += ste_rxns_lst

            # Print log message for reaction
            log = log1 + log2 + log3
            print(log)

        output_queue.put(srxns)
        print(f'Processor {os.getpid()} finished')

    # Dictionaries to map name to inchi
    name_ich_dct = mechanalyzer.parser.spc.name_inchi_dct(inp_mech_spc_dct)

    # Generate all stereo reactons from the initial set
    rxns = tuple(inp_mech_rxn_dct.keys())
    args = (name_ich_dct,)
    ste_rxns = execute_function_in_parallel(_expand, rxns, args, nprocs=nprocs)

    print('\nGenerating mech and spc from '
          'list of final stereoexpanded reactions')
    print('WARNING: Orig labeling of mech+spc not used')

    # Update the mechanism objects with unique spc and rxns
    ste_spc_dct, ste_rxn_dct = {}, {}
    ste_spc_dct, _ = update_spc_dct_from_reactions(ste_rxns, ste_spc_dct)
    ste_rxn_dct = update_rxn_dct(ste_rxns, ste_rxn_dct, ste_spc_dct)

    return ste_rxn_dct, ste_spc_dct


def remove_stereochemistry(inp_mech_rxn_dct, inp_mech_spc_dct):
    """ Generate a mechanism with all stereochemistry removed
    """

    print('Removing stereochemistry from the species and reactions')

    # Generate a spc_dct with no stereochemical labels
    noste_spc_dct = {}
    noste_ichs = ()
    removed_spcs = ()
    for name, dct in inp_mech_spc_dct.items():
        noste_ich = automol.inchi.standard_form(dct['inchi'], stereo=False)
        if noste_ich not in noste_ichs:
            _dct = copy.deepcopy(dct)
            _dct['inchi'] = noste_ich
            noste_spc_dct[name] = _dct
            noste_ichs += (noste_ich,)
        else:
            removed_spcs += (name,)

    name_ich_dct = mechanalyzer.parser.spc.name_inchi_dct(noste_spc_dct)

    # Now put in the reactions
    noste_rxn_dct = {}
    noste_rxns = ()
    removed_rxns = ()
    for rxn, params in inp_mech_rxn_dct.items():
        rxn_ich = _rxn_name_to_ich(rxn, name_ich_dct)
        if rxn_ich is not None:
            if rxn_ich not in noste_rxns:
                noste_rxn_dct[rxn] = params
                noste_rxns += (rxn_ich,)
            else:
                removed_rxns += (rxn,)
        else:
            removed_rxns += (rxn,)

    # Print the final
    print('\nSpecies:')
    for name in noste_spc_dct:
        print(name)

    print('\nReactions:')
    for rxn in noste_rxn_dct:
        print(rxn)

    print('\nRemoved spc and reactions')
    for name in removed_spcs:
        print(name)
    print()
    for rxn in removed_rxns:
        print(rxn)

    return noste_rxn_dct, noste_spc_dct


# Build reaction lists
def _ste_rxn_lsts(rxn_ich):
    """ Build reaction onjects
    """

    # Build reaction objects
    rxn_obj_sets = automol.reac.util.rxn_objs_from_inchi(
        rxn_ich[0], rxn_ich[1])
    rxn_obj = rxn_obj_sets[0][0]  # expand just with rxn object

    # Build a list of stereo reactions
    ste_rxn_ichs = ()
    for ste_rxn in automol.reac.expand_stereo(rxn_obj):
        rct_gras = automol.reac.reactant_graphs(ste_rxn)
        prd_gras = automol.reac.product_graphs(ste_rxn)
        try:
            rct_ichs = tuple(map(automol.graph.stereo_inchi, rct_gras))
            prd_ichs = tuple(map(automol.graph.stereo_inchi, prd_gras))

            ste_rxn_ichs += ((rct_ichs, prd_ichs),)
        except:
            print('Fail to get stereo', rxn_ich)

    # Set log message
    log = f' - Reaction identified as {rxn_obj.class_}.\n'

    return ste_rxn_ichs, log


# Functions to check and sort the reactions by stereochemistry
def _remove_enantiomer_reactions(ste_rxn_lst):
    """ Take all reactions that occur from stereochemically
        and determine which reactions should be kept and
        whihc are unneccessary
    """

    # Remove redundant sets and rebuild proper list
    f_ste_rxn_lst = automol.inchi.filter_enantiomer_reactions(ste_rxn_lst)

    # Print the removed reactions
    removed_ste_rxn_lst = set(ste_rxn_lst) - set(f_ste_rxn_lst)

    return f_ste_rxn_lst, removed_ste_rxn_lst


# Formatters and printers
def _stereo_results(rxn, f_ste_rxns_lst, removed_ste_rxns_lst):
    """ Print the final filtered reactions and those removed
    """

    # Print final list of reactions
    log = f' - Stereochemical Versions of Reaction: {rxn_name_str(rxn)}\n'
    for ste_rxn in f_ste_rxns_lst:
        log += '    ' + rxn_name_str(ste_rxn, newline=True) + '\n'

    # Print removed reactions
    if removed_ste_rxns_lst:
        log += (' - Redundant, enantiomeric reactions '
                'precluded from final list\n')
        for ste_rxn in removed_ste_rxns_lst:
            log += '    ' + rxn_name_str(ste_rxn, newline=True) + '\n'

    return log


def _add_third(rxn_lst, thrdbdy):
    """ Format a rxn list to have the third-body added back
    """
    return tuple((rxn[0], rxn[1], thrdbdy) for rxn in rxn_lst)


def _rxn_name_to_ich(rxn, ich_dct):
    """ Convert a reacion written with spc names to spc inchis
        Third body list remains the same
    """

    # Convert reactant and product names to InChIs
    _rxn = (
        tuple(ich_dct.get(rgt) for rgt in rxn[0]),
        tuple(ich_dct.get(rgt) for rgt in rxn[1]),
        rxn[2]
    )

    # Set rxn_ich to None
    if (
        any(rgt is None for rgt in _rxn[0]) or
        any(rgt is None for rgt in _rxn[1])
    ):
        _rxn = None

    return _rxn


def _rxn_smiles(rxn):
    """ write a reaction into smles
    """
    return (
        tuple(automol.inchi.smiles(rgt) for rgt in rxn[0]),
        tuple(automol.inchi.smiles(rgt) for rgt in rxn[1]),
    )
