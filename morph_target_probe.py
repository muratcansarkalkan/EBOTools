#!/usr/bin/env python3
import argparse
from . import multi_morph_core
def main():
    p=argparse.ArgumentParser()
    p.add_argument("base"); p.add_argument("morph")
    a=p.parse_args()
    print(multi_morph_core.describe_inventory(a.base,a.morph))
if __name__=="__main__": main()
