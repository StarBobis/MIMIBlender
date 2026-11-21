# Naraka sculpt export and native post-skin correspondence

The native post-skin exporter originally bound only captured positions and edge
midpoints (1e-7 position tolerance). Moving vertices by merged sculpting broke
that positional binding. Native resources also rebuilt the captured positions,
so relaxing binding alone would discard the sculpt at runtime.

When position binding fails, the exporter now accepts a unique source or edge
midpoint UV correspondence within 1e-7. Multiple distinct parent tuples sharing
that UV are rejected; changed normals are not proof of identity. The existing
triangle source-ownership validation still runs. This supports position-only
sculpting with preserved UV identity, not arbitrary remeshing or UV editing.

The exported displacement from the parent mean is added to each positive bone
term's local position. The original simulation and subtractive bone*g terms
remain unchanged. This defines the sculpt as a bone-transported offset on top
of native motion; it does not change the simulation's rest shape. Unchanged
positions within 1e-7 keep the historical resource bytes.

Validation: `python tools/test_naraka_native_postskin_data.py`. Synthetic cases
cover displaced unique-UV vertices, ambiguous UV rejection, source triangle
ownership, and signed influence evaluation for original vertices and midpoints
across all four depth modes and inactive batches. Three real-capture tests are
opt-in through the environment variables documented in that test file. No game
visual validation or user model reproduction was performed for this change.
