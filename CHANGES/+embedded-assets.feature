Added flatcontainer endpoints for embedded package assets, like nuget.org's:
``{id}/{version}/icon`` and ``{id}/{version}/readme`` serve the files declared by the
.nuspec ``<icon>`` and ``<readme>`` elements, extracted from the stored .nupkg. Search
and registration responses now point ``iconUrl`` at the icon endpoint for packages
with an embedded icon, so clients and UIs display it without external hosting.
