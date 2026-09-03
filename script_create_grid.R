# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Construit la grille SAFRAN en points et en mailles, depuis le fichier de
# coordonnées publié par Météo-France.
#
# La source est ce fichier et non SIM2.shp : le shapefile est un contour de la
# France qui ne couvre que 8 813 des 9 892 points de la grille, Corse comprise.
# Le fichier de coordonnées, lui, correspond exactement aux données.

library(sf)

grille_csv <- "resources/safran-grille_2026-09-03.csv"
sortie <- "resources/grid-SIM.gpkg"
maille <- 8000  # mètres

coords <- read.csv2(grille_csv, dec = ",")
names(coords) <- c("lambx_hm", "lamby_hm", "lat", "lon")
coords$x <- coords$lambx_hm * 100
coords$y <- coords$lamby_hm * 100

points <- st_as_sf(coords[, c("x", "y", "lat", "lon")],
                   coords = c("x", "y"), crs = 27572, remove = FALSE)

cellules <- st_sf(
    st_drop_geometry(points),
    geometry = st_sfc(lapply(seq_len(nrow(points)), function(i) {
        x <- points$x[i]; y <- points$y[i]
        st_polygon(list(rbind(
            c(x - maille/2, y - maille/2), c(x + maille/2, y - maille/2),
            c(x + maille/2, y + maille/2), c(x - maille/2, y + maille/2),
            c(x - maille/2, y - maille/2))))
    }), crs = 27572))

st_write(points, sortie, layer = "points", delete_layer = TRUE, quiet = TRUE)
st_write(cellules, sortie, layer = "grid-cells", delete_layer = TRUE, quiet = TRUE)

cat(nrow(points), "points écrits dans", sortie, "\n")
cat("emprise :", paste(round(st_bbox(cellules)), collapse = " "), "\n")
