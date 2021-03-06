#!/usr/bin/env python
import argparse
import os
import pandas as pd
from common import fileopen
from compute_simulated_accuracy import summary_fields

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="-")
    parser.add_argument("-o", "--output")
    parser.add_argument("-n", "--name", default="table")
    parser.add_argument("-c", "--caption", default="")
    parser.add_argument(
        "-e", "--error-rate-file", 
        help="Table generated by adjust_error_profiles.R that maps requested"
             "to actual error rates. Required for latex output.")
    parser.add_argument(
        "-t", "--tool-name-file",
        help="File that maps profile names to display names for tools")
    parser.add_argument(
        "-f", "--formats", choices=('txt', 'tex', 'pickle'), nargs="+",
        default=['tex'])
    args = parser.parse_args()
    
    with fileopen(args.input, 'rt') as inp:
        table = pd.read_csv(inp, sep="\t", names=summary_fields)
    
    if 'txt' in args.formats:
        with fileopen(args.output + '.txt', 'wt') as out:
            table.to_csv(out, sep="\t", index=False)
        
    if 'pickle' in args.formats:
        import pickle
        with fileopen(args.output + '.pickle', 'wb') as out:
            pickle.dump(table, out, protocol=pickle.HIGHEST_PROTOCOL)
    
    if 'tex' in args.formats:
        import numpy as np
        
        adapter_cols = (
            "non-adapter reads trimmed",
            "adapter reads overtrimmed",
            "total adapter reads undertrimmed")
        adapter_pct_cols = tuple('pct' + col for col in adapter_cols)
        base_cols = (
            "overtrimmed bases",
            "undertrimmed bases")
        total_cols = (
            "reads total error",
            "bases total error")
        all_cols = adapter_cols + adapter_pct_cols + base_cols + total_cols
        new_cols = (
            "Wrongly Trimmed",
            "Over-trimmed",
            "Under-trimmed",
            "Wrongly Trimmed",
            "Over-trimmed",
            "Under-trimmed",
            "Over-trimmed",
            "Under-trimmed",
            "Total Error", 
            "Total Error"
        )
        col_map = dict(zip(all_cols, new_cols))
        
        # Since we're evaluating adatper trimming accurracy, the number of threads 
        # don't matter (there's no randomness, so the results should be the same for
        # every run), and we don't want to consider any quality trimming.
        textable = table[(table.threads==4) & (table.qcut==0)]
        # Add additional columns
        textable["total adapter reads undertrimmed"] = (
            textable["adapter reads untrimmed"] + 
            textable["adapter reads undertrimmed"])
        for adapter_col, adapter_pct_col in zip(adapter_cols, adapter_pct_cols):
            textable[adapter_pct_col] = textable[adapter_col] / textable['retained reads']
        textable["reads total error"] = textable.loc[:,adapter_cols].apply(sum, 1) / textable['retained reads']
        textable["bases total error"] = textable.loc[:,base_cols].apply(sum, 1) / textable['total ref bases']
        # Melt into tidy format
        textable = textable.melt(id_vars=['dataset', 'program'], value_vars=all_cols)
        # Add the "level" - reads/read pct/bases
        def to_level(var):
            if 'pct' in var:
                return 'pct'
            elif 'reads' in var:
                return 'reads'
            else:
                return 'bases'
        textable['datalevel'] = list(to_level(var) for var in textable.variable)
        # Replace the variable names with those we want in the final table
        textable = textable.replace({ 'variable' : col_map })
        # Finally, pivot the table into the grouped format we want to use in the latex template and sort
        textable = textable.pivot_table(index=['dataset', 'program'], columns=['datalevel', 'variable']).sort_index()
        # Drop the unnecessary first column level
        textable.columns = textable.columns.droplevel(0)
        
        # Replace dataset names with actual error rates
        if args.error_rate_file:
            with open(args.error_rate_file, 'rt') as inp:
                error_rate_table = pd.read_csv(inp, sep="\t")
            error_rate_table = error_rate_table.groupby('Requested').agg(np.mean)
            datasets = textable.index.levels[0]
            textable.index = textable.index.set_levels(
                datasets.map(lambda x: str(round(error_rate_table.loc[x,'Actual'], 3))).values, 
                'dataset')
        
        # Replace tool names with display versions
        if args.tool_name_file:
            with open(args.tool_name_file, 'rt') as inp:
                tool_name_table = pd.read_csv(inp, sep="\t", index_col='ProfileName')
            programs = textable.index.levels[1]
            textable.index = textable.index.set_levels(
                programs.map(lambda x: tool_name_table.loc[x, 'DisplayName']).values, 
                'program')
        
        # Now render the template
        from mako import exceptions
        from mako.template import Template
        table_template = Template(filename=os.path.join(
            os.path.dirname(__file__), "simulated_accuracy_table.tex"))
        tex_file = args.output + ".tex"
        with fileopen(tex_file, "wt") as o:
            try:
                o.write(table_template.render(
                    name=args.name, caption=args.caption, table=textable))
            except:
                print(exceptions.text_error_template().render())


if __name__ == "__main__":
    main()
