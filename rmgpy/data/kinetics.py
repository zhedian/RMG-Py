#!/usr/bin/python
# -*- coding: utf-8 -*-

################################################################################
#
#   RMG - Reaction Mechanism Generator
#
#   Copyright (c) 2002-2010 Prof. William H. Green (whgreen@mit.edu) and the
#   RMG Team (rmg_dev@mit.edu)
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the 'Software'),
#   to deal in the Software without restriction, including without limitation
#   the rights to use, copy, modify, merge, publish, distribute, sublicense,
#   and/or sell copies of the Software, and to permit persons to whom the
#   Software is furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.
#
################################################################################

import os
import os.path
import logging
import codecs

from base import *

from rmgpy.chem.reaction import Reaction, ReactionError
from rmgpy.chem.kinetics import *
from rmgpy.chem.pattern import BondPattern, MoleculePattern, ActionError
from rmgpy.chem.molecule import Bond

################################################################################

class UndeterminableKineticsError(ReactionError):
    """
    An exception raised when attempts to estimate appropriate kinetic parameters
    for a chemical reaction are unsuccessful.
    """
    def __init__(self, reaction, message=''):
        new_message = 'Kinetics could not be determined. '+message
        ReactionError.__init__(self,reaction,new_message)

class InvalidActionError(Exception):
    """
    An exception to be raised when an invalid action is encountered in a
    reaction recipe.
    """
    pass

################################################################################

class ReactionRecipe:
    """
    Represent a list of actions that, when executed, result in the conversion
    of a set of reactants to a set of products. There are currently five such
    actions:

    ============= ============================= ================================
    Action Name   Arguments                     Description
    ============= ============================= ================================
    CHANGE_BOND   `center1`, `order`, `center2` change the bond order of the bond between `center1` and `center2` by `order`; do not break or form bonds
    FORM_BOND     `center1`, `order`, `center2` form a new bond between `center1` and `center2` of type `order`
    BREAK_BOND    `center1`, `order`, `center2` break the bond between `center1` and `center2`, which should be of type `order`
    GAIN_RADICAL  `center`, `radical`           increase the number of free electrons on `center` by `radical`
    LOSE_RADICAL  `center`, `radical`           decrease the number of free electrons on `center` by `radical`
    ============= ============================= ================================

    The actions are stored as a list in the `actions` attribute. Each action is
    a list of items; the first is the action name, while the rest are the
    action parameters as indicated above.
    """

    def __init__(self, actions=None):
        self.actions = actions or []

    def addAction(self, action):
        """
        Add an `action` to the reaction recipe, where `action` is a list
        containing the action name and the required parameters, as indicated in
        the table above.
        """
        self.actions.append(action)

    def getReverse(self):
        """
        Generate a reaction recipe that, when applied, does the opposite of
        what the current recipe does, i.e., it is the recipe for the reverse
        of the reaction that this is the recipe for.
        """
        other = ReactionRecipe()
        for action in self.actions:
            if action[0] == 'CHANGE_BOND':
                other.addAction(['CHANGE_BOND', action[1], str(-int(action[2])), action[3]])
            elif action[0] == 'FORM_BOND':
                other.addAction(['BREAK_BOND', action[1], action[2], action[3]])
            elif action[0] == 'BREAK_BOND':
                other.addAction(['FORM_BOND', action[1], action[2], action[3]])
            elif action[0] == 'LOSE_RADICAL':
                other.addAction(['GAIN_RADICAL', action[1], action[2]])
            elif action[0] == 'GAIN_RADICAL':
                other.addAction(['LOSE_RADICAL', action[1], action[2]])
        return other

    def __apply(self, struct, doForward, unique):
        """
        Apply the reaction recipe to the set of molecules contained in
        `structure`, a single Structure object that contains one or more
        structures. The `doForward` parameter is used to indicate
        whether the forward or reverse recipe should be applied. The atoms in
        the structure should be labeled with the appropriate atom centers.
        """

        pattern = isinstance(struct, MoleculePattern)

        for action in self.actions:
            if action[0] in ['CHANGE_BOND', 'FORM_BOND', 'BREAK_BOND']:

                # We are about to change the connectivity of the atoms in
                # struct, which invalidates any existing vertex connectivity
                # information; thus we reset it
                struct.resetConnectivityValues()

                label1, info, label2 = action[1:]

                # Find associated atoms
                atom1 = struct.getLabeledAtom(label1)
                atom2 = struct.getLabeledAtom(label2)
                if atom1 is None or atom2 is None or atom1 is atom2:
                    raise InvalidActionError('Invalid atom labels encountered.')

                # Apply the action
                if action[0] == 'CHANGE_BOND':
                    info = int(info)
                    bond = struct.getBond(atom1, atom2)
                    if doForward:
                        atom1.applyAction(['CHANGE_BOND', label1, info, label2])
                        atom2.applyAction(['CHANGE_BOND', label1, info, label2])
                        bond.applyAction(['CHANGE_BOND', label1, info, label2])
                    else:
                        atom1.applyAction(['CHANGE_BOND', label1, -info, label2])
                        atom2.applyAction(['CHANGE_BOND', label1, -info, label2])
                        bond.applyAction(['CHANGE_BOND', label1, -info, label2])
                elif (action[0] == 'FORM_BOND' and doForward) or (action[0] == 'BREAK_BOND' and not doForward):
                    bond = BondPattern(order=['S']) if pattern else Bond(order='S')
                    struct.addBond(atom1, atom2, bond)
                    atom1.applyAction(['FORM_BOND', label1, info, label2])
                    atom2.applyAction(['FORM_BOND', label1, info, label2])
                elif (action[0] == 'BREAK_BOND' and doForward) or (action[0] == 'FORM_BOND' and not doForward):
                    if not struct.hasBond(atom1, atom2):
                        raise InvalidActionError('Attempted to remove a nonexistent bond.')
                    bond = struct.getBond(atom1, atom2)
                    struct.removeBond(atom1, atom2)
                    atom1.applyAction(['BREAK_BOND', label1, info, label2])
                    atom2.applyAction(['BREAK_BOND', label1, info, label2])

            elif action[0] in ['LOSE_RADICAL', 'GAIN_RADICAL']:

                label, change = action[1:]
                change = int(change)

                # Find associated atom
                atom = struct.getLabeledAtom(label)
                if atom is None:
                    raise InvalidActionError('Unable to find atom with label "%s" while applying reaction recipe.' % label)

                # Apply the action
                for i in range(change):
                    if (action[0] == 'GAIN_RADICAL' and doForward) or (action[0] == 'LOSE_RADICAL' and not doForward):
                        atom.applyAction(['GAIN_RADICAL', label, 1])
                    elif (action[0] == 'LOSE_RADICAL' and doForward) or (action[0] == 'GAIN_RADICAL' and not doForward):
                        atom.applyAction(['LOSE_RADICAL', label, 1])

            else:
                raise InvalidActionError('Unknown action "' + action[0] + '" encountered.')

        struct.updateConnectivityValues()

    def applyForward(self, struct, unique=True):
        """
        Apply the forward reaction recipe to `molecule`, a single
        :class:`Molecule` object.
        """
        return self.__apply(struct, True, unique)

    def applyReverse(self, struct, unique=True):
        """
        Apply the reverse reaction recipe to `molecule`, a single
        :class:`Molecule` object.
        """
        return self.__apply(struct, False, unique)

################################################################################

def saveEntry(f, entry):
    """
    Save an `entry` in the kinetics database by writing a string to
    the given file object `f`.
    """

    def sortEfficiencies(efficiencies0):
        efficiencies = {}
        for mol, eff in efficiencies0.iteritems():
            smiles = mol.toSMILES()
            efficiencies[smiles] = eff
        keys = efficiencies.keys()
        keys.sort()
        return [(key, efficiencies[key]) for key in keys]

    f.write('entry(\n')
    f.write('    index = %i,\n' % (entry.index))
    if entry.label != '':
        f.write('    label = "%s",\n' % (entry.label))

    if isinstance(entry.item, Reaction):
        for i, reactant in enumerate(entry.item.reactants):
            f.write('    reactant%i = \n' % (i+1))
            f.write('"""\n')
            f.write(reactant.toAdjacencyList(removeH=True))
            f.write('""",\n')
        for i, product in enumerate(entry.item.products):
            f.write('    product%i = \n' % (i+1))
            f.write('"""\n')
            f.write(product.toAdjacencyList(removeH=True))
            f.write('""",\n')
        f.write('    degeneracy = %i,\n' % (entry.item.degeneracy))
    elif isinstance(entry.item, MoleculePattern):
        f.write('    group = \n')
        f.write('"""\n')
        f.write(entry.item.toAdjacencyList())
        f.write('""",\n')
    elif isinstance(entry.item, LogicNode):
        f.write('    group = "%s",\n' % (entry.item))
    else:
        raise InvalidDatabaseError("Encountered unexpected item of type %s while saving database." % (entry.item.__class__))

    if isinstance(entry.data, Arrhenius):
        f.write('    kinetics = Arrhenius(\n')
        f.write('        A = %r,\n' % (entry.data.A))
        f.write('        n = %r,\n' % (entry.data.n))
        f.write('        Ea = %r,\n' % (entry.data.Ea))
        f.write('        T0 = %r,\n' % (entry.data.T0))
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        f.write('    ),\n')
    elif isinstance(entry.data, ArrheniusEP):
        f.write('    kinetics = ArrheniusEP(\n')
        f.write('        A = %r,\n' % (entry.data.A))
        f.write('        n = %r,\n' % (entry.data.n))
        f.write('        alpha = %r,\n' % (entry.data.alpha))
        f.write('        E0 = %r,\n' % (entry.data.E0))
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        f.write('    ),\n')
    elif isinstance(entry.data, MultiArrhenius):
        f.write('    kinetics = MultiArrhenius(\n')
        f.write('        arrheniusList = [\n')
        for arrh in entry.data.arrheniusList:
            f.write('            %r,\n' % (arrh))
        f.write('        ],\n')
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        f.write('    ),\n')
    elif isinstance(entry.data, PDepArrhenius):
        f.write('    kinetics = PDepArrhenius(\n')
        f.write('        pressures = %r,\n' % (entry.data.pressures))
        f.write('        arrhenius = [\n')
        for arrh in entry.data.arrhenius:
            f.write('            %r,\n' % (arrh))
        f.write('        ],\n')
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        if entry.data.Pmin is not None: f.write('        Pmin = %r,\n' % (entry.data.Pmin))
        if entry.data.Pmax is not None: f.write('        Pmax = %r,\n' % (entry.data.Pmax))
        f.write('    ),\n')
    elif isinstance(entry.data, Troe):
        f.write('    kinetics = Troe(\n')
        f.write('        arrheniusHigh = %r,\n' % (entry.data.arrheniusHigh))
        f.write('        arrheniusLow = %r,\n' % (entry.data.arrheniusLow))
        f.write('        efficiencies = {%s},\n' % (', '.join(['"%s": %g' % (label, eff) for label, eff in sortEfficiencies(entry.data.efficiencies)])))
        f.write('        alpha = %r,\n' % (entry.data.alpha))
        f.write('        T3 = %r,\n' % (entry.data.T3))
        f.write('        T1 = %r,\n' % (entry.data.T1))
        if entry.data.T2 is not None: f.write('        T2 = %r,\n' % (entry.data.T2))
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        if entry.data.Pmin is not None: f.write('        Pmin = %r,\n' % (entry.data.Pmin))
        if entry.data.Pmax is not None: f.write('        Pmax = %r,\n' % (entry.data.Pmax))
        f.write('    ),\n')
    elif isinstance(entry.data, Lindemann):
        f.write('    kinetics = Lindemann(\n')
        f.write('        arrheniusHigh = %r,\n' % (entry.data.arrheniusHigh))
        f.write('        arrheniusLow = %r,\n' % (entry.data.arrheniusLow))
        f.write('        efficiencies = {%s},\n' % (', '.join(['"%s": %g' % (label, eff) for label, eff in sortEfficiencies(entry.data.efficiencies)])))
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        if entry.data.Pmin is not None: f.write('        Pmin = %r,\n' % (entry.data.Pmin))
        if entry.data.Pmax is not None: f.write('        Pmax = %r,\n' % (entry.data.Pmax))
        f.write('    ),\n')
    elif isinstance(entry.data, ThirdBody):
        f.write('    kinetics = ThirdBody(\n')
        f.write('        arrheniusHigh = %r,\n' % (entry.data.arrheniusHigh))
        f.write('        efficiencies = {%s},\n' % (', '.join(['"%s": %g' % (label, eff) for label, eff in sortEfficiencies(entry.data.efficiencies)])))
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        if entry.data.Pmin is not None: f.write('        Pmin = %r,\n' % (entry.data.Pmin))
        if entry.data.Pmax is not None: f.write('        Pmax = %r,\n' % (entry.data.Pmax))
        f.write('    ),\n')
    elif isinstance(entry.data, Chebyshev):
        f.write('    kinetics = Chebyshev(\n')
        f.write('        coeffs = [\n')
        for i in range(entry.data.degreeT):
            f.write('            [%s],\n' % (','.join(['%g' % (self.coeffs[i,j]) for j in range(self.degreeP)])))
        f.write('        ],\n')
        if entry.data.Tmin is not None: f.write('        Tmin = %r,\n' % (entry.data.Tmin))
        if entry.data.Tmax is not None: f.write('        Tmax = %r,\n' % (entry.data.Tmax))
        if entry.data.Pmin is not None: f.write('        Pmin = %r,\n' % (entry.data.Pmin))
        if entry.data.Pmax is not None: f.write('        Pmax = %r,\n' % (entry.data.Pmax))
        f.write('    ),\n')
    else:
        f.write('    kinetics = %r,\n' % (entry.data))

    f.write('    reference = %r,\n' % (entry.reference))
    f.write('    referenceType = "%s",\n' % (entry.referenceType))
    f.write('    shortDesc = """%s""",\n' % (entry.shortDesc))
    f.write('    longDesc = \n')
    f.write('"""\n')
    f.write(entry.longDesc)
    f.write('""",\n')

    f.write('    history = [\n')
    for time, user, action, description in entry.history:
        f.write('        ("%s","%s","%s","""%s"""),\n' % (time, user, action, description))
    f.write('    ],\n')

    f.write(')\n\n')

################################################################################

class KineticsDepository(Database):
    """
    A class for working with an RMG kinetics depository.
    """

    def __init__(self, label='', name='', shortDesc='', longDesc=''):
        Database.__init__(self, label=label, name=name, shortDesc=shortDesc, longDesc=longDesc)

    def loadEntry(self, index, label, molecule, kinetics, reference=None, referenceType='', shortDesc='', longDesc='', history=None):
        self.entries[index] = Entry(
            index = index,
            label = label,
            item = Molecule().fromAdjacencyList(molecule),
            data = kinetics,
            reference = reference,
            referenceType = referenceType,
            shortDesc = shortDesc,
            longDesc = longDesc.strip(),
            history = history or [],
        )

    def saveEntry(self, f, entry):
        """
        Write the given `entry` in the thermo database to the file object `f`.
        """
        return saveEntry(f, entry)

################################################################################

class KineticsLibrary(Database):
    """
    A class for working with an RMG kinetics library.
    """

    def __init__(self, label='', name='', shortDesc='', longDesc=''):
        Database.__init__(self, label=label, name=name, shortDesc=shortDesc, longDesc=longDesc)

    def loadEntry(self, index, reactant1, product1, kinetics, reactant2=None, reactant3=None, product2=None, product3=None, degeneracy=1, label='', reference=None, referenceType='', shortDesc='', longDesc='', history=None):
        reactants = [Molecule().fromAdjacencyList(reactant1)]
        if reactant2 is not None: reactants.append(Molecule().fromAdjacencyList(reactant2))
        if reactant3 is not None: reactants.append(Molecule().fromAdjacencyList(reactant3))

        products = [Molecule().fromAdjacencyList(product1)]
        if product2 is not None: products.append(Molecule().fromAdjacencyList(product2))
        if product3 is not None: products.append(Molecule().fromAdjacencyList(product3))

        self.entries[index] = Entry(
            index = index,
            label = label,
            item = Reaction(reactants=reactants, products=products, degeneracy=degeneracy),
            data = kinetics,
            reference = reference,
            referenceType = referenceType,
            shortDesc = shortDesc,
            longDesc = longDesc.strip(),
            history = history or [],
        )

    def saveEntry(self, f, entry):
        """
        Write the given `entry` in the kinetics library to the file object `f`.
        """
        return saveEntry(f, entry)

    def loadOld(self, path):
        """
        Load an old-style RMG kinetics library from the location `path`.
        """
        path = os.path.abspath(path)

        self.loadOldDictionary(os.path.join(path,'species.txt'), pattern=False)
        species = dict([(label, entry.item) for label, entry in self.entries.iteritems()])
        
        reactions = []
        reactions.extend(self.__loadOldReactions(os.path.join(path,'reactions.txt'), species))
        if os.path.exists(os.path.join(path,'pdepreactions.txt')):
            reactions.extend(self.__loadOldReactions(os.path.join(path,'pdepreactions.txt'), species))

        self.entries = {}
        for index, reaction in enumerate(reactions):
            self.entries[index+1] = Entry(
                index = index+1,
                item = reaction,
                data = reaction.kinetics,
            )
            reaction.kinetics = None

    def __loadOldReactions(self, path, species):
        """
        Load an old-style reaction library from `path`. This algorithm can
        handle both the pressure-independent and pressure-dependent reaction
        files. If the pressure-dependent file is read, the extra pressure-
        dependent kinetics information is ignored unless the kinetics database
        is a seed mechanism.
        """
        reactions = []

        # Process the reactions or pdepreactions file
        try:
            inUnitSection = False; inReactionSection = False
            Aunits = []; Eunits = ''
            reaction = None; kinetics = None

            fdict = open(path, 'r')
            for line in fdict:
                line = removeCommentFromLine(line).strip()
                if len(line) > 0:
                    if inUnitSection:
                        if 'A:' in line or 'E:' in line:
                            units = line.split()[1]
                            if 'A:' in line:
                                Aunits0 = units.split('/') # Assume this is a 3-tuple: moles or molecules, volume, time
                                Aunits0[1] = Aunits0[1][0:-1] # Remove '3' from e.g. 'm3' or 'cm3'; this is assumed
                                Aunits = [
                                    '',                                                         # Zeroth-order
                                    '%s^-1' % (Aunits0[2]),                                     # First-order
                                    '%s^3/(%s*%s)' % (Aunits0[1], Aunits0[0], Aunits0[2]),      # Second-order
                                    '%s^6/(%s^2*%s)' % (Aunits0[1], Aunits0[0], Aunits0[2]),    # Third-order
                                ]
                            elif 'E:' in line:
                                Eunits = units
                    elif inReactionSection:
                        reactants = []; products = []
                        if '=' in line:
                            # This line contains a reaction equation, (high-P) Arrhenius parameters, and uncertainties

                            # Strip out "(+M)" from line
                            line = line.replace("(+M)", "")

                            items = line.split()

                            # Find the reaction arrow
                            for arrow in ['<=>', '=>', '=', '->']:
                                if arrow in items:
                                    arrowIndex = items.index(arrow)
                                    break

                            # Find the start of the data
                            try:
                                temp = float(items[-6])
                                dataIndex = -6
                            except ValueError:
                                dataIndex = -3

                            # Find the reactant and product items
                            reactantItems = []
                            for item in items[0:arrowIndex]:
                                if item != '+':
                                    for i in item.split('+'):
                                        if i != '' and i != 'M': reactantItems.append(i)
                            productItems = []
                            for item in items[arrowIndex+1:dataIndex]:
                                if item != '+':
                                    for i in item.split('+'):
                                        if i != '' and i != 'M': productItems.append(i)
                            
                            for item in reactantItems:
                                try:
                                    reactants.append(species[item])
                                except KeyError:
                                    raise DatabaseError('Reactant %s not found in species dictionary.' % item)
                            for item in productItems:
                                try:
                                    products.append(species[item])
                                except KeyError:
                                    raise DatabaseError('Product %s not found in species dictionary.' % item)

                            if dataIndex == -6:
                                A = constants.Quantity((float(items[-6]), Aunits[len(reactants)]))
                                n = constants.Quantity((float(items[-5]), ''))
                                Ea = constants.Quantity((float(items[-4]), Eunits))
                            else:
                                A = constants.Quantity((float(items[-3]), Aunits[len(reactants)]))
                                n = constants.Quantity((float(items[-2]), ''))
                                Ea = constants.Quantity((float(items[-1]), Eunits))
                            kinetics = Arrhenius(A=A, n=n, Ea=Ea, T0=(1.0,"K"))

                            reaction = Reaction(
                                reactants=reactants,
                                products=products,
                                kinetics=kinetics,
                                reversible=(arrow in ['<=>', '=']),
                            )
                            reactions.append(reaction)

                        elif 'LOW' in line:
                            # This line contains low-pressure-limit Arrhenius parameters in Chemkin format

                            # Upgrade the kinetics to a Lindemann if not already done
                            if isinstance(kinetics, ThirdBody):
                                kinetics = Lindemann(arrheniusHigh=kinetics.arrheniusHigh, efficiencies=kinetics.efficiencies)
                                reaction.kinetics = kinetics
                            elif isinstance(kinetics, Arrhenius):
                                kinetics = Lindemann(arrheniusHigh=kinetics)
                                reaction.kinetics = kinetics

                            items = line.split('/')
                            A, n, Ea = items[1].split()
                            A = constants.Quantity((float(A), Aunits[len(reactants)]))
                            n = constants.Quantity((float(n), ''))
                            Ea = constants.Quantity((float(Ea), Eunits))
                            kinetics.arrheniusLow = Arrhenius(A=A, n=n, Ea=Ea, T0=1.0)

                        elif 'TROE' in line:
                            # This line contains Troe falloff parameters in Chemkin format

                            # Upgrade the kinetics to a Troe if not already done
                            if isinstance(kinetics, Lindemann):
                                kinetics = Troe(arrheniusLow=kinetics.arrheniusLow, arrheniusHigh=kinetics.arrheniusHigh, efficiencies=kinetics.efficiencies)
                                reaction.kinetics = kinetics
                            elif isinstance(kinetics, ThirdBody):
                                kinetics = Troe(arrheniusHigh=kinetics.arrheniusHigh, efficiencies=kinetics.efficiencies)
                                reaction.kinetics = kinetics
                            elif isinstance(kinetics, Arrhenius):
                                kinetics = Troe(arrheniusHigh=kinetics)
                                reaction.kinetics = kinetics

                            items = line.split('/')
                            items = items[1].split()
                            if len(items) == 3:
                                alpha, T3, T1 = items; T2 = None
                            else:
                                alpha, T3, T1, T2 = items

                            kinetics.alpha = constants.Quantity(float(alpha))
                            kinetics.T1 = constants.Quantity((float(T1),"K"))
                            if T2 is not None:
                                kinetics.T2 = constants.Quantity((float(T2),"K"))
                            else:
                                kinetics.T2 = None
                            kinetics.T3 = constants.Quantity((float(T3),"K"))

                        else:
                            # This line contains collider efficiencies

                            # Upgrade the kinetics to a ThirdBody if not already done
                            if isinstance(kinetics, Arrhenius):
                                kinetics = ThirdBody(arrheniusHigh=kinetics)
                                reaction.kinetics = kinetics

                            items = line.split('/')
                            for spec, eff in zip(items[0::2], items[1::2]):
                                spec = str(spec).strip()

                                # In old database, N2, He, Ne, and Ar were treated as special "bath gas" species
                                # These bath gas species were not required to be in the species dictionary
                                # The new database removes this special case, and requires all colliders to be explicitly defined
                                # This is hardcoding to handle these special colliders
                                if spec.upper() in ['N2', 'HE', 'AR', 'NE'] and spec not in species:
                                    if spec.upper() == 'N2':
                                        species[spec] = Molecule().fromSMILES('N#N')
                                    elif spec.upper() == 'HE':
                                        species[spec] = Molecule().fromAdjacencyList('1 He 0')
                                    elif spec.upper() == 'AR':
                                        species[spec] = Molecule().fromAdjacencyList('1 Ar 0')
                                    elif spec.upper() == 'NE':
                                        species[spec] = Molecule().fromAdjacencyList('1 Ne 0')
                                
                                if spec not in species:
                                    logging.warning('Collider %s for reaction %s not found in species dictionary.' % (spec, reaction))
                                else:
                                    kinetics.efficiencies[species[spec]] = float(eff)

                    if 'Unit:' in line:
                        inUnitSection = True; inReactionSection = False
                    elif 'Reactions:' in line:
                        inUnitSection = False; inReactionSection = True

        except (DatabaseError, InvalidAdjacencyListError), e:
            logging.exception(str(e))
            raise
        except IOError, e:
            logging.exception('Database dictionary file "' + e.filename + '" not found.')
            raise
        finally:
            if fdict: fdict.close()

        return reactions

################################################################################

class KineticsGroups(Database):
    """
    A class for working with an RMG kinetics group additivity database.
    In particular, each instance of this class represents a reaction family:
    a set of reactions with similar chemistry, and therefore similar reaction
    rates. The attributes are:

    =================== ======================= ================================
    Attribute           Type                    Description
    =================== ======================= ================================
    `forwardTemplate`   :class:`Reaction`       The forward reaction template
    `forwardRecipe`     :class:`ReactionRecipe` The steps to take when applying the forward reaction to a set of reactants
    `reverseTemplate`   :class:`Reaction`       The reverse reaction template
    `reverseRecipe`     :class:`ReactionRecipe` The steps to take when applying the reverse reaction to a set of reactants
    `forbidden`         ``dict``                (Optional) Forbidden product structures in either direction
    =================== ======================= ================================

    There are a few reaction families that are their own reverse (hydrogen
    abstraction and intramolecular hydrogen migration); for these
    `reverseTemplate` and `reverseRecipe` will both be ``None``.
    """

    def __init__(self, entries=None, top=None, label='', name='', shortDesc='', longDesc='', forwardTemplate=None, forwardRecipe=None, reverseTemplate=None, reverseRecipe=None, forbidden=None):
        Database.__init__(self, entries, top, label, name, shortDesc, longDesc)
        self.forwardTemplate = forwardTemplate
        self.forwardRecipe = forwardRecipe
        self.reverseTemplate = reverseTemplate
        self.reverseRecipe = reverseRecipe
        self.forbidden = forbidden
        self.ownReverse = forwardTemplate is not None and reverseTemplate is None

    def __str__(self):
        return '<ReactionFamily "%s">' % (self.label)

    def loadOld(self, path):
        """
        Load an old-style RMG kinetics group additivity database from the
        location `path`.
        """
        self.label = os.path.basename(path)
        self.name = self.label

        self.loadOldDictionary(os.path.join(path, 'dictionary.txt'), pattern=True)
        self.loadOldTree(os.path.join(path, 'tree.txt'))
        # The old kinetics groups use rate rules (not group additivity values),
        # so we can't load the old rateLibrary.txt

        # Load the reaction recipe
        self.loadOldTemplate(os.path.join(path, 'reactionAdjList.txt'))
        # Construct the forward and reverse templates
        reactants = [self.entries[label] for label in self.forwardTemplate.reactants]
        if self.ownReverse:
            self.forwardTemplate = Reaction(reactants=reactants, products=reactants)
            self.reverseTemplate = None
        else:
            products = self.generateProductTemplate(reactants)
            self.forwardTemplate = Reaction(reactants=reactants, products=products)
            self.reverseTemplate = Reaction(reactants=reactants, products=products)

        entries = self.top[:]
        for entry in self.top:
            entries.extend(self.descendants(entry))
        for index, entry in enumerate(entries):
            entry.index = index + 1

        return self

    def processOldLibraryEntry(self, data):
        """
        Process a list of parameters `data` as read from an old-style RMG
        thermo database, returning the corresponding kinetics object.
        """
        # This is hardcoding of reaction families!
        if self.label in ['H_Abstraction', 'R_Addition_MultipleBond', 'R_Recombination', 'HO2_Elimination_from_PeroxyRadical', 'Disproportionation', '1+2_Cycloaddition', '2+2_cycloaddition_Cd', '2+2_cycloaddition_CO', '2+2_cycloaddition_CCO', 'Diels_alder_addition', '1,2_Insertion', '1,3_Insertion_CO2', '1,3_Insertion_ROR', 'R_Addition_COm', 'Oa_R_Recombination']:
            Aunits = 'cm^3/(mol*s)'
        elif self.label in ['intra_H_migration', 'Birad_recombination', 'intra_OH_migration', 'Cyclic_Ether_Formation', 'Intra_R_Add_Exocyclic', 'Intra_R_Add_Endocyclic', '1,2-Birad_to_alkene', 'Intra_Disproportionation']:
            Aunits = 's^-1'
        else:
            raise ValueError('Unable to determine preexponential units for reaction family "%s".' % self.label)

        try:
            Tmin, Tmax = data[0].split('-')
            Tmin = (float(Tmin),"K")
            Tmax = (float(Tmax),"K")
        except ValueError:
            Tmin = None
            Tmax = None

        return ArrheniusEP(
            A = (float(data[1]),Aunits),
            n = float(data[2]),
            alpha = float(data[3]),
            E0 = (float(data[4]),"kcal/mol"),
            Tmin = Tmin,
            Tmax = Tmax,
        )

    def loadOldTemplate(self, path):
        """
        Load an old-style RMG reaction family template from the location `path`.
        """

        self.forwardTemplate = Reaction(reactants=[], products=[])
        self.forwardRecipe = ReactionRecipe()
        self.ownReverse = False

        ftemp = None
        # Process the template file
        try:
            ftemp = open(path, 'r')
            for line in ftemp:
                line = line.strip()
                if len(line) > 0 and line[0] == '(':
                    # This is a recipe action line
                    tokens = line.split()
                    action = [tokens[1]]
                    action.extend(tokens[2][1:-1].split(','))
                    self.forwardRecipe.addAction(action)
                elif 'thermo_consistence' in line:
                    self.ownReverse = True
                elif '->' in line:
                    # This is the template line
                    tokens = line.split()
                    atArrow = False
                    for token in tokens:
                        if token == '->':
                            atArrow = True
                        elif token != '+' and not atArrow:
                            self.forwardTemplate.reactants.append(token)
                        elif token != '+' and atArrow:
                            self.forwardTemplate.products.append(token)
        except IOError, e:
            logging.exception('Database template file "' + e.filename + '" not found.')
            raise
        finally:
            if ftemp: ftemp.close()

    def saveOld(self, path):
        """
        Save the old RMG kinetics groups to the given `path` on disk.
        """
        pass

    def loadEntry(self, index, label, group, kinetics, reference=None, referenceType='', shortDesc='', longDesc='', history=None):
        if group[0:3].upper() == 'OR{' or group[0:4].upper() == 'AND{' or group[0:7].upper() == 'NOT OR{' or group[0:8].upper() == 'NOT AND{':
            item = makeLogicNode(group)
        else:
            item = MoleculePattern().fromAdjacencyList(group)
        self.entries[label] = Entry(
            index = index,
            label = label,
            item = item,
            data = kinetics,
            reference = reference,
            referenceType = referenceType,
            shortDesc = shortDesc,
            longDesc = longDesc.strip(),
            history = history or [],
        )

    def load(self, path, local_context=None, global_context=None):
        """
        Load a thermodynamics database from a file located at `path` on disk.
        """
        local_context['recipe'] = self.loadRecipe
        local_context['template'] = self.loadTemplate
        local_context['True'] = True
        local_context['False'] = False
        Database.load(self, path, local_context, global_context)

        self.label = os.path.basename(os.path.splitext(path)[0])
        # Generate the reverse template if necessary
        self.forwardTemplate.reactants = [self.entries[label] for label in self.forwardTemplate.reactants]
        if self.ownReverse:
            self.reverseTemplate = None
            self.reverseRecipe = None
        else:
            self.forwardTemplate.products = self.generateProductTemplate(self.forwardTemplate.reactants)
            self.reverseTemplate = Reaction(reactants=self.forwardTemplate.products, products=self.forwardTemplate.reactants)
            self.reverseRecipe = self.forwardRecipe.getReverse()

        return self

    def loadTemplate(self, reactants, products, ownReverse=False):
        """
        Load information about the reaction template.
        """
        self.forwardTemplate = Reaction(reactants=reactants, products=products)
        self.ownReverse = ownReverse

    def loadRecipe(self, actions):
        """
        Load information about the reaction recipe.
        """
        # Remaining lines are reaction recipe for forward reaction
        self.forwardRecipe = ReactionRecipe()
        for action in actions:
            action[0] = action[0].upper()
            assert action[0] in ['CHANGE_BOND','FORM_BOND','BREAK_BOND','GAIN_RADICAL','LOSE_RADICAL']
            self.forwardRecipe.addAction(action)

    def saveEntry(self, f, entry):
        """
        Write the given `entry` in the thermo database to the file object `f`.
        """
        return saveEntry(f, entry)

    def save(self, path, entryName='entry'):
        """
        Save the current database to the file at location `path` on disk. The
        optional `entryName` parameter specifies the identifier used for each
        data entry.
        """
        entries = self.getEntriesToSave()
                
        # Write the header
        f = codecs.open(path, 'w', 'utf-8')
        f.write('name = "%s"\n' % (self.name))
        f.write('shortDesc = "%s"\n' % (self.shortDesc))
        f.write('longDesc = """\n')
        f.write(self.longDesc)
        f.write('\n"""\n\n')

        # Write the template
        f.write('template(reactants=[%s], products=[%s], ownReverse=%s)\n\n' % (
            ', '.join(['"%s"' % (entry.label) for entry in self.forwardTemplate.reactants]),
            ', '.join(['"%s"' % (entry.label) for entry in self.forwardTemplate.products]),
            self.ownReverse))

        # Write the recipe
        f.write('recipe(actions=[\n')
        for action in self.forwardRecipe.actions:
            f.write('    %r,\n' % (action))
        f.write('])\n\n')

        # Save the entries
        for entry in entries:
            self.saveEntry(f, entry)

        # Write the tree
        if len(self.top) > 0:
            f.write('tree(\n')
            f.write('"""\n')
            f.write(self.generateOldTree(self.top, 1))
            f.write('"""\n')
            f.write(')\n\n')

        f.close()

    def generateProductTemplate(self, reactants0):
        """
        Generate the product structures by applying the reaction template to
        the top-level nodes. For reactants defined by multiple structures, only
        the first is used here; it is assumed to be the most generic.
        """

        # First, generate a list of reactant structures that are actual
        # structures, rather than unions
        reactantStructures = []

        logging.log(0, "Generating template for products.")
        for reactant in reactants0:
            if isinstance(reactant, list):  reactants = [reactant[0]]
            else:                           reactants = [reactant]

            logging.log(0, "Reactants:%s"%reactants)
            for s in reactants: #
                struct = s.item
                if isinstance(struct, LogicNode):
                    all_structures = struct.getPossibleStructures(self.entries)
                    logging.log(0, 'Expanding node %s to %s'%(s, all_structures))
                    reactantStructures.append(all_structures)
                else:
                    reactantStructures.append([struct])

        # Second, get all possible combinations of reactant structures
        reactantStructures = getAllCombinations(reactantStructures)
        
        # Third, generate all possible product structures by applying the
        # recipe to each combination of reactant structures
        # Note that bimolecular products are split by labeled atoms
        productStructures = []
        for reactantStructure in reactantStructures:
            productStructure = self.applyRecipe(reactantStructure, forward=True, unique=False)
            productStructures.append(productStructure)

        # Fourth, remove duplicates from the lists
        productStructureList = [[] for i in range(len(productStructures[0]))]
        for productStructure in productStructures:
            for i, struct in enumerate(productStructure):
                for s in productStructureList[i]:
                    try:
                        if s.isIsomorphic(struct): break
                    except KeyError:
                        print struct.toAdjacencyList()
                        print s.toAdjacencyList()
                        raise
                else:
                    productStructureList[i].append(struct)

        # Fifth, associate structures with product template
        productSet = []
        for index, products in enumerate(productStructureList):
            label = self.forwardTemplate.products[index]
            if len(products) == 1:
                entry = Entry(
                    label = label,
                    item = products[0],
                )
                self.entries[entry.label] = entry
                productSet.append(entry)
            else:
                item = []
                counter = 0
                for product in products:
                    entry = Entry(
                        label = '%s%i' % (label,counter+1),
                        item = product,
                    )
                    item.append(entry.label)
                    self.entries[entry.label] = entry
                    counter += 1

                item = LogicOr(item,invert=False)
                entry = Entry(
                    label = label,
                    item = item,
                )
                self.entries[entry.label] = entry
                counter += 1
                productSet.append(entry)

        return productSet

    def reactantMatch(self, reactant, templateReactant):
        """
        Return ``True`` if the provided reactant matches the provided
        template reactant and ``False`` if not, along with a complete list of
        the identified mappings.
        """
        mapsList = []
        if templateReactant.__class__ == list: templateReactant = templateReactant[0]
        struct = self.dictionary[templateReactant]

        if isinstance(struct, LogicNode):
            for child_structure in struct.getPossibleStructures(self.dictionary):
                ismatch, mappings = reactant.findSubgraphIsomorphisms(child_structure)
                if ismatch:
                    mapsList.extend(mappings)
            return len(mapsList) > 0, mapsList
        elif isinstance(struct, Molecule):
            return reactant.findSubgraphIsomorphisms(struct)

    def applyRecipe(self, reactantStructures, forward=True, unique=True):
        """
        Apply the recipe for this reaction family to the list of
        :class:`Molecule` objects `reactantStructures`. The atoms
        of the reactant structures must already be tagged with the appropriate
        labels. Returns a list of structures corresponding to the products
        after checking that the correct number of products was produced.
        """

        # There is some hardcoding of reaction families in this function, so
        # we need the label of the reaction family for this
        label = self.label.lower()

        # Merge reactant structures into single structure
        # Also copy structures so we don't modify the originals
        # Since the tagging has already occurred, both the reactants and the
        # products will have tags
        if isinstance(reactantStructures[0], MoleculePattern):
            reactantStructure = MoleculePattern()
        else:
            reactantStructure = Molecule()
        for s in reactantStructures:
            reactantStructure = reactantStructure.merge(s.copy(deep=True))

        # Hardcoding of reaction family for radical recombination (colligation)
        # because the two reactants are identical, they have the same tags
        # In this case, we must change the labels from '*' and '*' to '*1' and
        # '*2'
        if label == 'r_recombination' and forward:
            identicalCenterCounter = 0
            for atom in reactantStructure.atoms:
                if atom.label == '*':
                    identicalCenterCounter += 1
                    atom.label = '*' + str(identicalCenterCounter)
            if identicalCenterCounter != 2:
                raise Exception('Unable to change labels from "*" to "*1" and "*2" for reaction family %s.' % (label))

        # Generate the product structure by applying the recipe
        if forward:
            self.forwardRecipe.applyForward(reactantStructure, unique)
        else:
            self.reverseRecipe.applyForward(reactantStructure, unique)
        productStructure = reactantStructure

        # Hardcoding of reaction family for reverse of radical recombination
        # (Unimolecular homolysis)
        # Because the two products are identical, they should the same tags
        # In this case, we must change the labels from '*1' and '*2' to '*' and
        # '*'
        if label == 'r_recombination' and not forward:
            for atom in productStructure.atoms:
                if atom.label == '*1' or atom.label == '*2': atom.label = '*'

        # If reaction family is its own reverse, relabel atoms
        if not self.reverseTemplate:
            # Get atom labels for products
            atomLabels = {}
            for atom in productStructure.atoms:
                if atom.label != '':
                    atomLabels[atom.label] = atom

            # This is hardcoding of reaction families (bad!)
            label = self.label.lower()
            if label == 'h_abstraction':
                # '*2' is the H that migrates
                # it moves from '*1' to '*3'
                atomLabels['*1'].label = '*3'
                atomLabels['*3'].label = '*1'

            elif label == 'intra_h_migration':
                # '*3' is the H that migrates
                # swap the two ends between which the H moves
                atomLabels['*1'].label = '*2'
                atomLabels['*2'].label = '*1'
                # reverse all the atoms in the chain between *1 and *2
                # i.e. swap *4 with the highest, *5 with the second-highest
                highest = len(atomLabels)
                if highest>4:
                    for i in range(4,highest+1):
                        atomLabels['*%d'%i].label = '*%d'%(4+highest-i)

        if not forward: template = self.reverseTemplate
        else:           template = self.forwardTemplate

        # Split product structure into multiple species if necessary
        productStructures = productStructure.split()
        for product in productStructures:
            product.updateConnectivityValues()

        # Make sure we've made the expected number of products
        if len(template.products) != len(productStructures):
            # We have a different number of products than expected by the template.
            # It might be because we found a ring-opening using a homolysis template
            if (label=='r_recombination' and not forward
             and len(productStructures) == 1
             and len(reactantStructures) == 1):
                # just be absolutely sure (maybe slow, but safe)
                rs = reactantStructures[0]
                if ( rs.isVertexInCycle(rs.getLabeledAtom('*1'))
                 and rs.isVertexInCycle(rs.getLabeledAtom('*2'))):
                    # both *1 and *2 are in cycles (probably the same one)
                    # so it's pretty safe to just fail quietly,
                    # and try the next reaction
                    return None

            # no other excuses, raise an exception
            message = 'Application of reaction recipe failed; expected %s product(s), but %s found.\n' % (len(template.products), len(productStructures))
            message += "Reaction family: %s \n"% (self)
            message += "Reactant structures: %s \n" % (reactantStructures)
            message += "Product structures: %s \n" % (productStructures)
            message += "Template: %s" % (template)
            logging.error(message)
            #return None # don't fail!!! muhahaha
            raise Exception(message)

        # If there are two product structures, place the one containing '*1' first
        if len(productStructures) == 2:
            if not productStructures[0].containsLabeledAtom('*1') and \
                productStructures[1].containsLabeledAtom('*1'):
                productStructures.reverse()

        # If product structures are Molecule objects, update their atom types
        for struct in productStructures:
            if isinstance(struct, Molecule):
                struct.updateAtomTypes()

        # Return the product structures
        return productStructures

    def __generateProductStructures(self, reactantStructures, maps, forward):
        """
        For a given set of `reactantStructures` and a given set of `maps`,
        generate and return the corresponding product structures. The
        `reactantStructures` parameter should be given in the order the
        reactants are stored in the reaction family template. The `maps`
        parameter is a list of mappings of the top-level tree node of each
        *template* reactant to the corresponding *structure*. This function
        returns the product structures, species, and a boolean that tells
        whether any species are new.
        """

        if not forward: template = self.reverseTemplate
        else:           template = self.forwardTemplate

        # Clear any previous atom labeling from all reactant structures
        for struct in reactantStructures: struct.clearLabeledAtoms()

        # If there are two structures and they are the same, then make a copy
        # of the second one and adjust the second map to point to its atoms
        # This is for the case where A + A --> products
        if len(reactantStructures) == 2 and reactantStructures[0] == reactantStructures[1]:
            reactantStructures[1] = reactantStructures[1].copy(deep=True)
            newMap = {}
            for reactantAtom, templateAtom in maps[1].iteritems():
                index = reactantStructures[0].atoms.index(reactantAtom)
                newMap[reactantStructures[1].atoms[index]] = templateAtom
            maps[1] = newMap

        # Tag atoms with labels
        for map in maps:
            for reactantAtom, templateAtom in map.iteritems():
                reactantAtom.label = templateAtom.label

        # Generate the product structures by applying the forward reaction recipe
        try:
            productStructures = self.applyRecipe(reactantStructures, forward=forward)
            if not productStructures: return None
        except InvalidActionError, e:
            print 'Unable to apply reaction recipe!'
            print 'Reaction family is %s in %s direction' % (self.label, 'forward' if forward else 'reverse')
            print 'Reactant structures are:'
            for struct in reactantStructures:
                print struct.toAdjacencyList()
            raise

        # If there are two product structures, place the one containing '*1' first
        if len(productStructures) == 2:
            if not productStructures[0].containsLabeledAtom('*1') and \
                productStructures[1].containsLabeledAtom('*1'):
                productStructures.reverse()

        # Check that reactant and product structures are allowed in this family
        # If not, then stop
        if self.forbidden is not None:
            for label, struct2 in self.forbidden.iteritems():
                for struct in reactantStructures:
                    if struct.isSubgraphIsomorphic(struct2): return None
                for struct in productStructures:
                    if struct.isSubgraphIsomorphic(struct2): return None

        return productStructures

    def __createReaction(self, reactants, products, isForward):
        """
        Create and return a new :class:`Reaction` object containing the
        provided `reactants` and `products` as lists of :class:`Molecule`
        objects.
        """

        # Make sure the products are in fact different than the reactants
        if len(reactants) == len(products) == 1:
            if reactants[0].isIsomorphic(products[0]):
                return None
        elif len(reactants) == len(products) == 2:
            if reactants[0].isIsomorphic(products[0]) and reactants[1].isIsomorphic(products[1]):
                return None
            elif reactants[0].isIsomorphic(products[1]) and reactants[1].isIsomorphic(products[0]):
                return None

        # We need to save the reactant and product structures with atom labels so
        # we can generate the kinetics
        # We make copies so the structures aren't trampled on by later actions
        reactants = [reactant.copy(deep=True) for reactant in reactants]
        products = [product.copy(deep=True) for product in products]
        for reactant in reactants:
            reactant.updateAtomTypes()
            reactant.updateConnectivityValues()
        for product in products:
            product.updateAtomTypes()
            product.updateConnectivityValues()

        # Create and return reaction object
        return Reaction(reactants=reactants, products=products)

    def __matchReactantToTemplate(self, reactant, templateReactant):
        """
        Return ``True`` if the provided reactant matches the provided
        template reactant and ``False`` if not, along with a complete list of the
        mappings.
        """

        if isinstance(templateReactant, list): templateReactant = templateReactant[0]
        struct = templateReactant.item
        
        if isinstance(struct, LogicNode):
            mappings = []
            for child_structure in struct.getPossibleStructures(self.entries):
                ismatch, map = reactant.findSubgraphIsomorphisms(child_structure)
                if ismatch: mappings.extend(map)
            return len(mappings) > 0, mappings
        elif isinstance(struct, MoleculePattern):
            return reactant.findSubgraphIsomorphisms(struct)

    def generateReactions(self, reactants, forward=True):
        """
        Generate a list of all of the possible reactions of this family between
        the list of `reactants`. The number of reactants provided must match
        the number of reactants expected by the template, or this function
        will return an empty list. Each item in the list of reactants should
        be a list of :class:`Molecule` objects, each representing a resonance
        isomer of the species of interest.
        """

        rxnList = []; speciesList = []

        for index in range(len(reactants)):
            if not isinstance(reactants[index], list):
                reactants[index] = [reactants[index]]

        # Reactants must have explicit hydrogen atoms
        implicitH = []
        for reactant in reactants:
            implicit = []
            for isomer in reactant:
                implicit.append(isomer.implicitHydrogens)
                isomer.makeHydrogensExplicit()
            implicitH.append(implicit)

        if forward: template = self.forwardTemplate
        elif not forward and self.reverseTemplate is not None: template = self.reverseTemplate
        else: return rxnList

        # Unimolecular reactants: A --> products
        if len(reactants) == 1 and len(template.reactants) == 1:

            # Iterate over all resonance isomers of the reactant
            for molecule in reactants[0]:

                ismatch, mappings = self.__matchReactantToTemplate(molecule, template.reactants[0])
                if ismatch:
                    for map in mappings:
                        reactantAtomLabels = [{}]
                        for atom1, atom2 in map.iteritems():
                            reactantAtomLabels[0][atom1.label] = atom2

                        reactantStructures = [molecule]
                        productStructures = self.__generateProductStructures(reactantStructures, [map], forward)
                        if productStructures:
                            rxn = self.__createReaction(reactantStructures, productStructures, forward)
                            if rxn: rxnList.append(rxn)

        # Bimolecular reactants: A + B --> products
        elif len(reactants) == 2 and len(template.reactants) == 2:

            moleculesA = reactants[0]
            moleculesB = reactants[1]

            # Iterate over all resonance isomers of the reactant
            for moleculeA in moleculesA:
                for moleculeB in moleculesB:

                    # Reactants stored as A + B
                    ismatchA, mappingsA = self.__matchReactantToTemplate(moleculeA, template.reactants[0])
                    ismatchB, mappingsB = self.__matchReactantToTemplate(moleculeB, template.reactants[1])

                    # Iterate over each pair of matches (A, B)
                    if ismatchA and ismatchB:
                        for mapA in mappingsA:
                            for mapB in mappingsB:

                                reactantAtomLabels = [{},{}]
                                for atom1, atom2 in mapA.iteritems():
                                    reactantAtomLabels[0][atom1.label] = atom2
                                for atom1, atom2 in mapB.iteritems():
                                    reactantAtomLabels[1][atom1.label] = atom2

                                reactantStructures = [moleculeA, moleculeB]
                                productStructures = self.__generateProductStructures(reactantStructures, [mapA, mapB], forward)
                                if productStructures:
                                    rxn = self.__createReaction(reactantStructures, productStructures, forward)
                                    if rxn: rxnList.append(rxn)

                    # Only check for swapped reactants if they are different
                    if reactants[0] is not reactants[1]:

                        # Reactants stored as B + A
                        ismatchA, mappingsA = self.__matchReactantToTemplate(moleculeA, template.reactants[1])
                        ismatchB, mappingsB = self.__matchReactantToTemplate(moleculeB, template.reactants[0])

                        # Iterate over each pair of matches (A, B)
                        if ismatchA and ismatchB:
                            for mapA in mappingsA:
                                for mapB in mappingsB:

                                    reactantAtomLabels = [{},{}]
                                    for atom1, atom2 in mapA.iteritems():
                                        reactantAtomLabels[0][atom1.label] = atom2
                                    for atom1, atom2 in mapB.iteritems():
                                        reactantAtomLabels[1][atom1.label] = atom2

                                    reactantStructures = [moleculeA, moleculeB]
                                    productStructures = self.__generateProductStructures(reactantStructures, [mapA, mapB], forward)
                                    if productStructures:
                                        rxn = self.__createReaction(reactantStructures, productStructures, forward)
                                        if rxn: rxnList.append(rxn)

        # Remove duplicates from the reaction list
        index0 = 0
        while index0 < len(rxnList):

            # Generate resonance isomers for products of the current reaction
            products = [product.generateResonanceIsomers() for product in rxnList[index0].products]

            index = index0 + 1
            while index < len(rxnList):
                # We know the reactants are the same, so we only need to compare the products
                match = False
                if len(rxnList[index].products) == len(products) == 1:
                    for product in products[0]:
                        if rxnList[index].products[0].isIsomorphic(product):
                            match = True
                            break
                elif len(rxnList[index].products) == len(products) == 2:
                    for productA in products[0]:
                        for productB in products[1]:
                            if rxnList[index].products[0].isIsomorphic(productA) and rxnList[index].products[1].isIsomorphic(productB):
                                match = True
                                break
                            elif rxnList[index].products[0].isIsomorphic(productB) and rxnList[index].products[1].isIsomorphic(productA):
                                match = True
                                break

                # If we found a match, remove it from the list
                # Also increment the reaction path degeneracy of the remaining reaction
                if match:
                    rxnList.remove(rxnList[index])
                    rxnList[index0].degeneracy += 1
                else:
                    index += 1

            index0 += 1

        # For R_Recombination reactions, the degeneracy is twice what it should
        # be, so divide those by two
        # This is hardcoding of reaction families!
        if self.label.lower() == 'unimolecular homolysis':
            for rxn in rxnList:
                rxn.degeneracy /= 2

        # Restore implicit hydrogen atoms if necessary
        for reactant, implicit in zip(reactants, implicitH):
            for isomer, H in zip(reactant, implicit):
                if H: isomer.makeHydrogensImplicit()

        # This reaction list has only checked for duplicates within itself, not
        # with the global list of reactions
        return rxnList

    def getReactionTemplate(self, reaction):
        """
        For a given `reaction` with properly-labeled :class:`Molecule` objects
        as the reactants, determine the most specific nodes in the tree that
        describe the reaction.
        """

        # Get forward reaction template and remove any duplicates
        forwardTemplate = self.top[:]

        temporary = []
        symmetricTree = False
        for entry in forwardTemplate:
            if entry not in temporary:
                temporary.append(entry)
            else:
                # duplicate node found at top of tree
                # eg. R_recombination: ['Y_rad', 'Y_rad']
                assert len(forwardTemplate)==2 , 'Can currently only do symmetric trees with nothing else in them'
                symmetricTree = True
        forwardTemplate = temporary

        # Descend reactant trees as far as possible
        template = []
        for entry in forwardTemplate:
            # entry is a top-level node that should be matched
            group = entry.item

            # To sort out "union" groups, descend to the first child that's not a logical node
            # ...but this child may not match the structure.
            # eg. an R3 ring node will not match an R4 ring structure.
            # (but at least the first such child will contain fewest labels - we hope)
            if isinstance(entry.item, LogicNode):
                group = entry.item.getPossibleStructures(self.entries)[0]

            atomList = group.getLabeledAtoms() # list of atom labels in highest non-union node

            for reactant in reaction.reactants:
                # Match labeled atoms
                # Check this reactant has each of the atom labels in this group
                if not all([reactant.containsLabeledAtom(label) for label in atomList]):
                    continue # don't try to match this structure - the atoms aren't there!
                # Match structures
                atoms = reactant.getLabeledAtoms()
                matched_node = self.descendTree(reactant, atoms, root=entry)
                if matched_node is not None:
                    template.append(matched_node)
                else:
                    logging.warning("Couldn't find match for %s in %s" % (entry,atomList))
                    logging.warning(reactant.toAdjacencyList())

        # Get fresh templates (with duplicate nodes back in)
        forwardTemplate = self.top[:]
        if self.label.lower() == 'r_recombination':
            forwardTemplate.append(forwardTemplate[0])

        # Check that we were able to match the template.
        # template is a list of the actual matched nodes
        # forwardTemplate is a list of the top level nodes that should be matched
        if len(template) != len(forwardTemplate):
            logging.warning('Unable to find matching template for reaction %s in reaction family %s' % (str(reaction), str(self)) )
            logging.warning(" Trying to match " + str(forwardTemplate))
            logging.warning(" Matched "+str(template))
            print str(self), template, forwardTemplate
            for reactant in reaction.reactants:
                print reactant.toAdjacencyList() + '\n'
            for product in reaction.products:
                print product.toAdjacencyList() + '\n'
            raise UndeterminableKineticsError(reaction)

        return template

    def getKinetics(self, reaction, structures):
        """
        Determine the appropriate kinetics for `reaction` which involves the
        labeled atoms in `atoms`.
        """

        template = self.getReactionTemplate(reaction)

        # climb the tree finding ancestors
        nodeLists = []
        for temp in template:
            nodeList = []
            while temp is not None:
                nodeList.append(temp)
                temp = self.tree.parent[temp]
            nodeLists.append(nodeList)

        # Generate all possible combinations of nodes
        items = getAllCombinations(nodeLists)

        # Generate list of kinetics at every node
        #logging.debug("   Template contains %s"%forwardTemplate)
        kinetics = []
        for item in items:
            itemData = self.library.getData(item)
            #logging.debug("   Looking for %s found %r"%(item, itemData))
            if itemData is not None:
                kinetics.append(itemData)

            if symmetric_tree: # we might only store kinetics the other way around
                item.reverse()
                itemData = self.library.getData(item)
                #logging.debug("   Also looking for %s found %r"%(item, itemData))
                if itemData is not None:
                    kinetics.append(itemData)

        # Make sure we've found at least one set of valid kinetics
        if len(kinetics) == 0:
            for reactant in structures:
                print reactant.toAdjacencyList() + '\n'
            raise UndeterminableKineticsError(reaction)

        # Choose the best kinetics
        # For now just return the kinetics with the highest index
        maxIndex = max([k.index for k in kinetics])
        kinetics = [k for k in kinetics if k.index == maxIndex][0]

        return kinetics.model


    def fitGroupValuesFromOldLibrary(self, path, Tlist):
        """
        Generate group additivity values for the reaction family using the
        rate rules in the old kinetics database at location `path` on disk.
        The group additivity values are generated at the set of temperatures
        `Tlist` in K.
        """

        # This function assumes that the rest of the old database has already been loaded

        # Parse the old library
        numLabels = max(len(self.forwardTemplate.reactants), len(self.top))
        entries = self.parseOldLibrary(os.path.join(path, 'rateLibrary.txt'), numParameters=10, numLabels=numLabels)

        kdata = []
        templates = []
        kunits = ''
        for labels, entry in entries.iteritems():
            kinetics = entry[1]
            if isinstance(kinetics, ArrheniusEP):
                if kinetics.alpha.value == 0:
                    templates.append([self.entries[group] for group in labels.split(';')])
                    kdata.append([kinetics.getRateCoefficient(T, 0) for T in Tlist])
                    kunits = kinetics.A.units
                else:
                    logging.warning('Skipping entry "%s" with nonzero value of alpha = %g.' % (labels, kinetics.alpha.value))
            else:
                logging.warning('Skipping entry "%s" with non-ArrheniusEP kinetics "%s".' % (labels, kinetics.__class__))
        assert kunits in ['s^-1', 'cm^3/(mol*s)']
        if kunits == 'cm^3/(mol*s)':
            kunits = 'm^3/(mol*s)'
        
        Tdata = numpy.array(Tlist, numpy.float64)
        kdata = numpy.array(kdata, numpy.float64)
        groupValues, groupUncertainties, groupCounts, kmodel = self.fitGroupValues(templates, Tdata, kdata, kunits)

        return groupValues, groupUncertainties, groupCounts, templates, kdata, kmodel

    def fitGroupValues(self, templates, Tdata, kdata, kunits):
        """
        Fit group additivity values based on a matrix of rate coefficient
        data `kdata` corresponding to a list of reaction `templates` and a
        set of temperatures `Tdata`. The provided rate coefficient data should
        be for the high-pressure limit and should be given on a per-site basis.
        The groups in the templates should also be in this reaction family's
        tree.
        """

        import scipy.stats

        kmodel = numpy.zeros_like(kdata)

        # Determine a complete list of the entries in the database, sorted as in the tree
        entries = self.top[:]
        for entry in self.top:
            entries.extend(self.descendants(entry))

        # Determine a unique list of the groups we will be able to fit parameters for
        groupList = []
        for template in templates:
            for group in template:
                if group not in self.top:
                    groupList.append(group)
                    groupList.extend(self.ancestors(group)[:-1])
        groupList = list(set(groupList))
        groupList.sort(key=lambda x: x.index)

        # Initialize dictionaries of fitted group values and uncertainties
        groupValues = {}; groupUncertainties = {}; groupCounts = {}
        for entry in entries:
            groupValues[entry] = []
            groupUncertainties[entry] = []
            groupCounts[entry] = []

        # Fit group values at each temperature
        for t, T in enumerate(Tdata):

            # Generate least-squares matrix and vector
            A = []; b = []
            for index, template in enumerate(templates):

                # Create every combination of each group and its ancestors with each other
                combinations = []
                for group in template:
                    groups = [group]; groups.extend(self.ancestors(group))
                    combinations.append(groups)
                combinations = getAllCombinations(combinations)
                # Add a row to the matrix for each combination
                for groups in combinations:
                    Arow = [1 if group in groups else 0 for group in groupList]
                    Arow.append(1)
                    brow = math.log10(kdata[index,t])
                    A.append(Arow); b.append(brow)
                    
            if len(A) == 0:
                logging.warning('Unable to fit kinetics groups for family "%s"; no valid data found.' % (self.label))
                return
            A = numpy.array(A)
            b = numpy.array(b)

            x, residues, rank, s = numpy.linalg.lstsq(A, b)
            
            # Determine error in each group (on log scale)
            stdev = numpy.zeros(len(groupList)+1, numpy.float64)
            count = numpy.zeros(len(groupList)+1, numpy.int)
            for index, template in enumerate(templates):
                kd = math.log10(kdata[index,t])
                km = x[-1] + sum([x[groupList.index(group)] for group in template if group in groupList])
                kmodel[index,t] = 10**km
                variance = (km - kd)**2
                for group in template:
                    groups = [group]; groups.extend(self.ancestors(group))
                    for g in groups:
                        if g not in self.top:
                            index = groupList.index(g)
                            stdev[index] += variance
                            count[index] += 1
                stdev[-1] += variance
                count[-1] += 1
            stdev = numpy.sqrt(stdev / (count - 1))
            ci = scipy.stats.t.ppf(0.975, count - 1) * stdev

            # Update dictionaries of fitted group values and uncertainties
            for entry in entries:
                if entry == self.top[0]:
                    groupValues[entry].append(10**x[-1])
                    groupUncertainties[entry].append(10**ci[-1])
                    groupCounts[entry].append(count[-1])
                elif entry in groupList:
                    index = groupList.index(entry)
                    groupValues[entry].append(10**x[index])
                    groupUncertainties[entry].append(10**ci[index])
                    groupCounts[entry].append(count[index])
                else:
                    groupValues[entry] = None
                    groupUncertainties[entry] = None
                    groupCounts[entry] = None

        # Store the fitted group values and uncertainties on the associated entries
        for entry in entries:
            if groupValues[entry] is not None:
                entry.data = KineticsData(Tdata=(Tdata,"K"), kdata=(groupValues[entry],kunits))
                entry.data.kdata.uncertainties = numpy.array(groupUncertainties[entry])
            else:
                entry.data = None

        return groupValues, groupUncertainties, groupCounts, kmodel

################################################################################

class KineticsDatabase:
    """
    A class for working with the RMG kinetics database.
    """

    def __init__(self):
        self.depository = {}
        self.libraries = {}
        self.groups = {}
        self.local_context = {
            'Arrhenius': Arrhenius,
            'ArrheniusEP': ArrheniusEP,
            'MultiArrhenius': MultiArrhenius,
            'PDepArrhenius': PDepArrhenius,
            'Chebyshev': Chebyshev,
            'ThirdBody': ThirdBody,
            'Lindemann': Lindemann,
            'Troe': Troe,
        }
        self.global_context = {}

    def load(self, path):
        """
        Load the kinetics database from the given `path` on disk, where `path`
        points to the top-level folder of the thermo database.
        """
        self.loadDepository(os.path.join(path, 'depository'))
        self.loadLibraries(os.path.join(path, 'libraries'))
        self.loadGroups(os.path.join(path, 'groups'))

    def loadDepository(self, path):
        """
        Load the kinetics database from the given `path` on disk, where `path`
        points to the top-level folder of the thermo database.
        """
        self.depository = {}
        for (root, dirs, files) in os.walk(os.path.join(path)):
            for f in files:
                if os.path.splitext(f)[1].lower() == '.py':
                    depository = KineticsDepository()
                    depository.load(os.path.join(root, f), self.local_context, self.global_context)
                    self.depository[depository.label] = depository

    def loadLibraries(self, path):
        """
        Load the kinetics database from the given `path` on disk, where `path`
        points to the top-level folder of the thermo database.
        """
        self.libraries = {}
        for (root, dirs, files) in os.walk(os.path.join(path)):
            for f in files:
                if os.path.splitext(f)[1].lower() == '.py':
                    library = KineticsLibrary()
                    library.load(os.path.join(root, f), self.local_context, self.global_context)
                    self.libraries[library.label] = library

    def loadGroups(self, path):
        """
        Load the kinetics database from the given `path` on disk, where `path`
        points to the top-level folder of the thermo database.
        """
        self.groups = {}
        for (root, dirs, files) in os.walk(os.path.join(path)):
            for f in files:
                if os.path.splitext(f)[1].lower() == '.py':
                    groups = KineticsGroups()
                    groups.load(os.path.join(root, f), self.local_context, self.global_context)
                    self.groups[groups.label] = groups

    def save(self, path):
        """
        Save the thermo database to the given `path` on disk, where `path`
        points to the top-level folder of the thermo database.
        """

        path = os.path.abspath(path)

        for label, depository in self.depository.iteritems():
            depository.save(os.path.join(path, 'depository', '%s.py' % label))

        for label, library in self.libraries.iteritems():
            folders = label.split(os.sep)
            try:
                os.makedirs(os.path.join(path, 'libraries', *folders[:-1]))
            except OSError:
                pass
            library.save(os.path.join(path, 'libraries', '%s.py' % label))

        for label, family in self.groups.iteritems():
            family.save(os.path.join(path, 'groups', '%s.py' % label))

    def loadOld(self, path):
        """
        Load the old RMG kinetics database from the given `path` on disk, where
        `path` points to the top-level folder of the old RMG database.
        """
        self.depository = {}
        self.libraries = {}
        self.groups = {}

        librariesPath = os.path.join(path, 'kinetics_libraries')
        for (root, dirs, files) in os.walk(os.path.join(path, 'kinetics_libraries')):
            if os.path.exists(os.path.join(root, 'species.txt')) and os.path.exists(os.path.join(root, 'reactions.txt')):
                library = KineticsLibrary(label=root[len(librariesPath)+1:], name=root[len(librariesPath)+1:])
                library.loadOld(root)
                self.libraries[library.label] = library
                
        for (root, dirs, files) in os.walk(os.path.join(path, 'kinetics_groups')):
            if os.path.exists(os.path.join(root, 'dictionary.txt')) and os.path.exists(os.path.join(root, 'rateLibrary.txt')):
                group = KineticsGroups(label=os.path.basename(root), name=os.path.basename(root))
                group.loadOld(root)
                self.groups[group.label] = group
                self.depository[group.label]  = KineticsDepository(label=group.label, name=group.name)

        return self

    def saveOld(self, path):
        """
        Save the old RMG kinetics database to the given `path` on disk, where
        `path` points to the top-level folder of the old RMG database.
        """
        pass

    def generateReactions(self, reactants, products=None):
        """
        Generate all reactions between the provided list of one or two
        `reactants`, which should be :class:`Molecule` objects. This method
        searches the depository, libraries, and groups, in that order.
        """
        reactionList = []
        reactionList.extend(self.generateReactionsFromDepository(reactants))
        reactionList.extend(self.generateReactionsFromLibraries(reactants))
        reactionList.extend(self.generateReactionsFromGroups(reactants))

        # Remove any reactions from the above that don't also involve *all* of the specified products
        if products is not None:
            reactionsToRemove = []
            for reaction in reactionList:
                rxn = reaction[0]
                products0 = [p for p in rxn.products]
                for product in products:
                    for product0 in products0:
                        if product.isIsomorphic(product0):
                            products0.remove(product0)
                            break
                if len(products0) != 0:
                    reactionsToRemove.append(reaction)
            for reaction in reactionsToRemove:
                reactionList.remove(reaction)

        return reactionList

    def __reactionMatchesReactants(self, reactants, reaction):
        """
        Return ``True`` if the given ``reactants`` represent the total set of
        reactants or products for the given ``reaction``, or ``False`` if not.
        The reactants should be :class:`Molecule` objects.
        """
        # Check forward direction
        if len(reactants) == len(reaction.reactants) == 1:
            if reactants[0].isIsomorphic(reaction.reactants[0]):
                return True
        elif len(reactants) == len(reaction.reactants) == 2:
            if reactants[0].isIsomorphic(reaction.reactants[0]) and reactants[1].isIsomorphic(reaction.reactants[1]):
                return True
            elif reactants[0].isIsomorphic(reaction.reactants[1]) and reactants[1].isIsomorphic(reaction.reactants[0]):
                return True

        # Check reverse direction
        if len(reactants) == len(reaction.products) == 1:
            if reactants[0].isIsomorphic(reaction.products[0]):
                return True
        elif len(reactants) == len(reaction.products) == 2:
            if reactants[0].isIsomorphic(reaction.products[0]) and reactants[1].isIsomorphic(reaction.products[1]):
                return True
            elif reactants[0].isIsomorphic(reaction.products[1]) and reactants[1].isIsomorphic(reaction.products[0]):
                return True

        # If we're here then neither direction matched, so return false
        return False

    def generateReactionsFromDepository(self, reactants, only_families=None):
        """
        Generate all reactions between the provided list of one or two
        `reactants`, which should be :class:`Molecule` objects. This method
        searches the depository.
        """
        reactionList = []
        for label, depository in self.depository.iteritems():
            if only_families is None or label in only_families:
                for entry in depository.entries.values():
                    if self.__reactionMatchesReactants(reactants, entry.item):
                        reactionList.append([entry.item, entry.data, depository, entry])
        return reactionList

    def generateReactionsFromLibraries(self, reactants):
        """
        Generate all reactions between the provided list of one or two
        `reactants`, which should be :class:`Molecule` objects. This method
        searches the depository.
        """
        reactionList = []
        for label, library in self.libraries.iteritems():
            reactionList.extend(self.generateReactionsFromLibrary(reactants, library))
        return reactionList

    def generateReactionsFromLibrary(self, reactants, library):
        """
        Generate all reactions between the provided list of one or two
        `reactants`, which should be :class:`Molecule` objects. This method
        searches the depository.
        """
        reactionList = []
        for entry in library.entries.values():
            if self.__reactionMatchesReactants(reactants, entry.item):
                reactionList.append([entry.item, entry.data, library, entry])
        return reactionList

    def generateReactionsFromGroups(self, reactants, only_families=None):
        """
        Generate all reactions between the provided list of one or two
        `reactants`, which should be :class:`Molecule` objects. This method
        searches the depository.
        """
        reactionList = []
        for label, family in self.groups.iteritems():
            if only_families is None or label in only_families:
                reactions = family.generateReactions(reactants, forward=True)
                for reaction in reactions:
                    reactionList.append([reaction, None, family, None])
                reactions = family.generateReactions(reactants, forward=False)
                for reaction in reactions:
                    reactionList.append([reaction, None, family, None])
        return reactionList

    def getKineticsData(self, reactants, products, family):
        """
        Return the kinetic parameters for a reaction involving lists of
        `reactants` and `products` and a string name of a reaction `family`.
        The reactant and product molecules should already have the appropriate
        reactive atoms labeled. This function first searches the loaded
        libraries in order, returning the first match found, before falling
        back to estimation via group additivity.
        """
        kineticsData = None
        # Check the libraries in order first; return the first successful match
        for label, library in self.libraries.iteritems():
            kineticsData = self.getKineticsDataFromLibrary(reactants, products, family, library)
            if kineticsData: break
        else:
            # Thermo not found in any loaded libraries, so estimate
            kineticsData = self.getKineticsDataFromGroups(reactants, products, family)
        return kineticsData

    def getAllKineticsData(self, reactants, products, family):
        """
        Return all possible sets of kinetic parameters for a reaction involving
        lists of `reactants` and `products` and a string name of a reaction
        `family`. The reactant and product molecules should already have the
        appropriate reactive atoms labeled. The hits from the depository come
        first, then the libraries (in order), and then the group additivity
        estimate. This method is useful for a generic search job.
        """
        kineticsData = []
        # Data from depository comes first
        kineticsData.append(self.getKineticsDataFromDepository(reactants, products, family))
        # Data from libraries comes second
        for label, library in self.libraries.iteritems():
            kineticsData.append(self.getKineticsDataFromLibrary(reactants, products, family, library))
        # Last entry is always the estimate from group additivity
        kineticsData.append(self.getKineticsDataFromGroups(reactants, products, family))
        return kineticsData

    def __equivalentReactions(self, reaction, reactants, products):
        """
        Return ``True`` if `reaction` has all of the given `reactants` and
        `products`.
        """
        if len(reaction.reactants) != len(reactants) or len(reaction.products) != len(products):
            return False

        reactantsMatch = False
        if len(reactants) == 1:
            reactantsMatch = reaction.reactants[0].isIsomorphic(reactants[0])
        elif len(reactants) == 2:
            reactantsMatch = (
                (reaction.reactants[0].isIsomorphic(reactants[0]) and reaction.reactants[1].isIsomorphic(reactants[1]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[1]) and reaction.reactants[1].isIsomorphic(reactants[0]))
            )
        elif len(reactants) == 3:
            reactantsMatch = (
                (reaction.reactants[0].isIsomorphic(reactants[0]) and reaction.reactants[1].isIsomorphic(reactants[1]) and reaction.reactants[2].isIsomorphic(reactants[2]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[0]) and reaction.reactants[1].isIsomorphic(reactants[2]) and reaction.reactants[2].isIsomorphic(reactants[1]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[1]) and reaction.reactants[1].isIsomorphic(reactants[0]) and reaction.reactants[2].isIsomorphic(reactants[2]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[1]) and reaction.reactants[1].isIsomorphic(reactants[2]) and reaction.reactants[2].isIsomorphic(reactants[0]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[2]) and reaction.reactants[1].isIsomorphic(reactants[0]) and reaction.reactants[2].isIsomorphic(reactants[1]))
                or
                (reaction.reactants[0].isIsomorphic(reactants[2]) and reaction.reactants[1].isIsomorphic(reactants[1]) and reaction.reactants[2].isIsomorphic(reactants[0]))
            )
        if not reactantsMatch: return False

        productsMatch = False
        if len(reactants) == 1:
            productsMatch = reaction.products[0].isIsomorphic(products[0])
        elif len(reactants) == 2:
            productsMatch = (
                (reaction.products[0].isIsomorphic(products[0]) and reaction.products[1].isIsomorphic(products[1]))
                or
                (reaction.products[0].isIsomorphic(products[1]) and reaction.products[1].isIsomorphic(products[0]))
            )
        elif len(reactants) == 3:
            productsMatch = (
                (reaction.products[0].isIsomorphic(products[0]) and reaction.products[1].isIsomorphic(products[1]) and reaction.products[2].isIsomorphic(products[2]))
                or
                (reaction.products[0].isIsomorphic(products[0]) and reaction.products[1].isIsomorphic(products[2]) and reaction.products[2].isIsomorphic(products[1]))
                or
                (reaction.products[0].isIsomorphic(products[1]) and reaction.products[1].isIsomorphic(products[0]) and reaction.products[2].isIsomorphic(products[2]))
                or
                (reaction.products[0].isIsomorphic(products[1]) and reaction.products[1].isIsomorphic(products[2]) and reaction.products[2].isIsomorphic(products[0]))
                or
                (reaction.products[0].isIsomorphic(products[2]) and reaction.products[1].isIsomorphic(products[0]) and reaction.products[2].isIsomorphic(products[1]))
                or
                (reaction.products[0].isIsomorphic(products[2]) and reaction.products[1].isIsomorphic(products[1]) and reaction.products[2].isIsomorphic(products[0]))
            )
        if not productsMatch: return False

        return True
        
    def getKineticsDataFromDepository(self, reactants, products, family):
        """
        Return all possible sets of kinetic parameters for a reaction involving
        lists of `reactants` and `products` and a string name of a reaction
        `family` from the depository. The reactant and product molecules should
        already have the appropriate reactive atoms labeled. If no depository
        is loaded, a :class:`DatabaseError` is raised.
        """
        items = []
        # First check the family that the reaction belongs to
        for label, entry in self.depository[family].dictionary.iteritems():
            if self.__equivalentReactions(entry.item, reactants, products):
                items.append(entry.data)
        return items

    def getKineticsDataFromLibrary(self, reactants, products, family, library):
        """
        Return all possible sets of kinetic parameters for a reaction involving
        lists of `reactants` and `products` and a string name of a reaction
        `family` from the specified kinetics `library`. The reactant and
        product molecules should already have the appropriate reactive atoms
        labeled. If `library` is a string, the list of libraries is searched
        for a library with that name. If no match is found in that library,
        ``None`` is returned. If no corresponding library is found, a
        :class:`DatabaseError` is raised.
        """
        # In kinetics libraries we don't deal with reaction families
        for label, entry in library.entries.iteritems():
            if self.__equivalentReactions(entry.item, reactants, products):
                return entry.data
        return None

    def getKineticsDataFromGroups(self, reactants, products, family):
        """
        Return all possible sets of kinetic parameters for a reaction involving
        lists of `reactants` and `products` and a string name of a reaction
        `family` by estimation using the group additivity values. The reactant
        and product molecules should already have the appropriate reactive
        atoms labeled. If no group additivity values are loaded, a
        :class:`DatabaseError` is raised.
        """
        raise NotImplementedError("Kinetics group additivity database has not yet been implemented!")
