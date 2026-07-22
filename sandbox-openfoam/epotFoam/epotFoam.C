/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2011-2016 OpenFOAM Foundation
    Copyright (C) 2019 OpenCFD Ltd.
-------------------------------------------------------------------------------
License
    This file is part of OpenFOAM.

    OpenFOAM is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    OpenFOAM is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
    FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
    for more details.

    You should have received a copy of the GNU General Public License
    along with OpenFOAM.  If not, see <http://www.gnu.org/licenses/>.

Application
    epotFoam

Description
    Transient solver for incompressible, laminar flow of electrically
    conducting Newtonian fluids under a uniform applied magnetic field,
    in the inductionless (low magnetic Reynolds number) approximation.

    Electric potential formulation:

        laplacian(PotE) = div(U x B0)
        J = sigma * (-grad(PotE) + U x B0)
        F = J x B0

    Transcribed from the appendix of:
        Tassone, A., "Magnetic induction and electric potential solvers
        for incompressible MHD flows", Proceedings of CFD with OpenSource
        Software, Chalmers, 2016. (developed for OpenFOAM-4.x)
    rebased onto icoFoam of OpenFOAM v2412; deviations from the appendix
    are limited to the v2412 icoFoam scaffolding (pEqn.solve call,
    printExecutionTime, header includes).

    The cell-centred current density is reconstructed from face fluxes
    with the conservative scheme of Ni et al. (2007) so that charge
    conservation holds discretely.

\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "pisoControl.H"

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

int main(int argc, char *argv[])
{
    argList::addNote
    (
        "Transient solver for incompressible, laminar MHD flow"
        " of conducting Newtonian fluids (electric potential formulation,"
        " inductionless approximation)."
    );

    #include "postProcess.H"

    #include "addCheckCaseOptions.H"
    #include "setRootCaseLists.H"
    #include "createTime.H"
    #include "createMesh.H"

    pisoControl piso(mesh);

    #include "createFields.H"
    #include "initContinuityErrs.H"

    // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

    Info<< "\nStarting time loop\n" << endl;

    // Lorentz force term initialization
    volVectorField lorentz =
        sigma*(-fvc::grad(PotE) ^ B0) + sigma*((U ^ B0) ^ B0);

    while (runTime.loop())
    {
        Info<< "Time = " << runTime.timeName() << nl << endl;

        #include "CourantNo.H"

        // Momentum predictor

        fvVectorMatrix UEqn
        (
            fvm::ddt(U)
          + fvm::div(phi, U)
          - fvm::laplacian(nu, U)
          - (1.0/rho)*lorentz // Lorentz term
        );

        if (piso.momentumPredictor())
        {
            solve(UEqn == -fvc::grad(p));
        }

        // --- PISO loop
        while (piso.correct())
        {
            volScalarField rAU(1.0/UEqn.A());
            volVectorField HbyA(constrainHbyA(rAU*UEqn.H(), U, p));
            surfaceScalarField phiHbyA
            (
                "phiHbyA",
                fvc::flux(HbyA)
              + fvc::interpolate(rAU)*fvc::ddtCorr(U, phi)
            );

            adjustPhi(phiHbyA, U, p);

            // Update the pressure BCs to ensure flux consistency
            constrainPressure(p, U, phiHbyA, rAU);

            // Non-orthogonal pressure corrector loop
            while (piso.correctNonOrthogonal())
            {
                // Pressure corrector

                fvScalarMatrix pEqn
                (
                    fvm::laplacian(rAU, p) == fvc::div(phiHbyA)
                );

                pEqn.setReference(pRefCell, pRefValue);

                pEqn.solve(p.select(piso.finalInnerIter()));

                if (piso.finalNonOrthogonalIter())
                {
                    phi = phiHbyA - pEqn.flux();
                }
            }

            #include "continuityErrs.H"

            U = HbyA - rAU*fvc::grad(p);
            U.correctBoundaryConditions();
        }

        // Interpolating cross product u x B over mesh faces
        surfaceScalarField psiub = fvc::interpolate(U ^ B0) & mesh.Sf();

        // Poisson equation for electric potential
        fvScalarMatrix PotEEqn
        (
            fvm::laplacian(PotE)
         ==
            fvc::div(psiub)
        );

        // Reference potential
        PotEEqn.setReference(PotERefCell, PotERefValue);

        // Solving Poisson equation
        PotEEqn.solve();

        // Computation of current density at cell faces
        surfaceScalarField jn = -(fvc::snGrad(PotE)*mesh.magSf()) + psiub;

        // Current density at face center
        surfaceVectorField jnv = jn*mesh.Cf();

        // Interpolation of current density at cell center
        volVectorField jfinal =
            fvc::surfaceIntegrate(jnv) - (fvc::surfaceIntegrate(jn)*mesh.C());

        // Update current density distribution and boundary condition
        jfinal.correctBoundaryConditions();

        // Lorentz force computation
        lorentz = sigma*(jfinal ^ B0);

        runTime.write();

        runTime.printExecutionTime(Info);
    }

    Info<< "End\n" << endl;

    return 0;
}


// ************************************************************************* //
