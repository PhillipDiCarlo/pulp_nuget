Added support for NuGet symbol packages (.snupkg): a new ``nuget.symbol_package``
content type, a ``SymbolPackagePublish/4.9.0`` service-index resource accepting
``dotnet nuget push`` of symbol packages, ``.snupkg`` downloads from the flat
container, and an SSQP symbol server at ``<distribution>/symbols/`` that serves the
portable PDBs to Visual Studio and ``dotnet-symbol``.
