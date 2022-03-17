""" Return the rates from a prompt dissociation process
"""

import mess_io
import mechanalyzer


def prompt_dissociation_ktp_dct(ped_inp_str, ped_out_str,
                                ped_ped_str, ped_ke_out_str,
                                hot_inp_str, hot_out_str, hot_log_str,
                                modeltype, bf_thresh,
                                temps, pressures):
    """ Parses the MESS files and generates the rate constants
        from a prompt dissociation process
    """

    # PARSE INFORMATION FROM FILES NEEDED TO PROMPT BRANCHING FRACTION
    # Names are in input mechanism names

    # Read: ped.inp:
    #  species names, energies 
    spc_blocks_ped = mess_io.reader.get_species(ped_inp_str)
    ped_spc, _ = mess_io.reader.ped.ped_names(ped_inp_str)  # can supply
    energy_dct, _, conn_lst_dct, _ = mess_io.reader.pes(ped_inp_str)

    # Read: rate_ped.out and ke_ped.out:
    #  energy barriers, dofs, fragment names
    ene_bw_dct = {}
    dof_dct = {}
    fragments_dct = {}
    for spc in ped_spc:
        reacs, prods = spc
        label = ((reacs,), (prods,), (None,))

        # Find the corresponding energy barrier
        barrier_label = mess_io.reader.find_barrier(conn_lst_dct, reacs, prods)
        try:
            ene_bw_dct[label] = energy_dct[barrier_label]-energy_dct[prods]
        except KeyError:
            ene_bw_dct[label] = energy_dct[reacs]-energy_dct[prods]

        # Derive dofs involved
        dof_info = mechanalyzer.calculator.statmodels.get_dof_info(
            spc_blocks_ped[prods], ask_for_ts=True)
        dof_dct[label] = dof_info
        fragments_dct[label] = mess_io.reader.dct_species_fragments(
            spc_blocks_ped)[prods]

    # Read ped.out file for product energy distributions
    ped_dct = mess_io.reader.ped.get_ped(ped_ped_str, ped_spc, energy_dct)

    # Read ke_ped.out file for energy density of each fragment
    dos_df = mess_io.reader.rates.dos_rovib(ped_ke_out_str)

    # Read the hotenergies output
    spc_blocks_hoten = mess_io.reader.get_species(hot_inp_str)
    hot_frag_dct = mess_io.reader.dct_species_fragments(spc_blocks_hoten)
    hot_spc = mess_io.reader.hoten.get_hot_species(hot_inp_str)  # can supply

    hoten_dct = mess_io.reader.hoten.extract_hot_branching(
        hot_log_str, hot_spc, list(spc_blocks_hoten.keys()),
        list(temps), list(pressures))

    # OBTAIN ALL OF THE RATE CONSTANTS FROM THE OUTPUT FILES
    # Read the thermal rates from both files
    rxn_ktp_dct = {}
    for mess_str in (ped_out_str, hot_out_str):
        rxn_ktp_dct.update(
            mess_io.reader.rates.get_rxn_ktp_dct(
                mess_str,
                filter_kts=True,
                filter_reaction_types=('fake', 'self',
                                       'loss', 'capture', 'reverse'),
                relabel_reactions=True,
                tmin=min(temps),
                tmax=max(temps),
                pmin=min(pressures),
                pmax=max(pressures)
            )
        )

    # Derive Branching Fractions, Calculate Prompt Rates
    # Merge Prompt Rates with Thermaal Rates
    prompt_rxns = ()
    full_prompt_rxn_ktp_dct = {}
    for spc in ped_spc:
        reacs, prods = spc
        _reacs = tuple(reacs.split('+'))
        _prods = tuple(prods.split('+'))

        label = ((reacs,), (prods,), (None,))
        relabel = (_reacs, _prods, (None,))
        _ped_label = '+'.join(label[0]) + '->' + '+'.join(label[1])

        ped_df = ped_dct[_ped_label]
        ene_bw = ene_bw_dct[label]
        # select the fragment of which you want the PED:
        # it is the one in common with hotspecies
        fragments = fragments_dct[label]
        try:
            frag1 = list(set(hot_spc).intersection(fragments))[0]
            frag2 = list(set(fragments).difference((frag1,)))[0]
        except IndexError:
            print('no superposition between PED fragments and hot fragments '
                  '- exiting now \n')
        
        # DERIVE PED OF THE HOT FRAGMENT
        ped_df_frag1_dct = mechanalyzer.builder.ped.ped_frag1(
            ped_df, frag1, frag2, (modeltype,),
            dos_df=dos_df, dof_info=dof_dct[label], ene_bw=ene_bw)

        # JOIN PED AND HOTEN -> DERIVE PRODUCTS BF
        bf_tp_dct = mechanalyzer.builder.bf.bf_tp_dct(
            (modeltype,), ped_df_frag1_dct, hoten_dct[frag1], bf_thresh,
            savefile=False)

        # Calculate Prompt Dissociation Rates
        frag_reacs_dct = mess_io.reader.dct_species_fragments(
            spc_blocks_ped)
        frag_reacs = frag_reacs_dct[spc[0]]

        prompt_rxn_ktp_dct = mechanalyzer.builder.bf.merge_bf_ktp(
                bf_tp_dct, rxn_ktp_dct[relabel],
                frag_reacs, frag1, frag2, hot_frag_dct)[modeltype]

        # Merge Prompt Rates with all current; Rates added if rxn is prev. found
        full_prompt_rxn_ktp_dct = mechanalyzer.calculator.rates.merge_rxn_ktp_dcts(
            full_prompt_rxn_ktp_dct,
            prompt_rxn_ktp_dct
        )

        prompt_rxns += (relabel,)

    # Remove the original reaction
    # Point of this function
    for rxn in prompt_rxns:
        print('pop reaction?', rxn)
        rxn_ktp_dct.pop(rxn)

    # Add in the prompt versions of the reactions
    rxn_ktp_dct.update(full_prompt_rxn_ktp_dct)

    return rxn_ktp_dct
