Added alternate content sources (``/acs/nuget/nuget/``): refreshing an ACS indexes a
feed's packages, and syncs then download packages from an ACS copy with the same
package id and version before falling back to their remote, while on_demand content
is streamed from an ACS copy first.
