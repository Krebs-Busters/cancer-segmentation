"""Medical image segmentation helper functions."""

from typing import List, Tuple

import jax.numpy as jnp
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import SimpleITK as sitk  # noqa: N813
from SimpleITK.SimpleITK import Image


def resample_image(
    input_image: Image,
    new_spacing: Tuple[float, float, float],
    interpolator: int,
    default_value: int,
) -> Image:
    """Resample the input scans.

    Adapted from
    https://github.com/AnnekeMeyer/zone-segmentation/blob/c1a5f584c10afd31cbe5356d7e2f4371cb880b06/utils.py#L113
    """
    cast_image_filter = sitk.CastImageFilter()
    cast_image_filter.SetOutputPixelType(sitk.sitkFloat32)
    input_image = cast_image_filter.Execute(input_image)

    old_size = input_image.GetSize()
    old_spacing = input_image.GetSpacing()
    new_width = old_spacing[0] / new_spacing[0] * old_size[0]
    new_height = old_spacing[1] / new_spacing[1] * old_size[1]
    new_depth = old_spacing[2] / new_spacing[2] * old_size[2]
    new_size = [int(new_width), int(new_height), int(new_depth)]

    min_filter = sitk.StatisticsImageFilter()
    min_filter.Execute(input_image)
    # min_value = min_filter.GetMinimum()

    filter = sitk.ResampleImageFilter()
    input_image.GetSpacing()
    filter.SetOutputSpacing(new_spacing)
    filter.SetInterpolator(interpolator)
    filter.SetOutputOrigin(input_image.GetOrigin())
    filter.SetOutputDirection(input_image.GetDirection())
    filter.SetSize(new_size)
    filter.SetDefaultPixelValue(default_value)
    out_image = filter.Execute(input_image)

    return out_image


def plot_box(box: List[np.ndarray]) -> None:
    """Plot a box as a matplotlib figure.

    Args:
        box (List[np.ndarray]): A list of lines
            as produced by the box_lines function.
    """
    fig = plt.figure()
    ax = fig.add_subplot(projection="3d")
    for linepos, line in enumerate(box):
        if linepos == 0:
            ax.plot(line[0, 0], line[0, 1], line[0, 2], "s")
        ax.plot(line[:, 0], line[:, 1], line[:, 2], "-.")
    plt.show()


origin = np.array([0, 0, 0])


def box_lines(size: np.ndarray, start: np.ndarray = origin) -> List[np.ndarray]:
    """Create a box of a given size.

    Args:
        size (np.ndarray): A 3d array which specifies the
            height, widht and depth of the box.
        start (np.ndarray): A 3d dimensional displacement
            vector for the bottom front edge of the box.
            Defaults to the origin at [0, 0, 0].

    Returns:
        List[np.ndarray]: A list of boundary lines,
            which form a box.
            Use the `plot_box` function to visualize
            what happens.
    """
    stop = start + size
    bc = np.array([start[0], start[1], start[2]])
    br = np.array([stop[0], start[1], start[2]])
    bl = np.array([start[0], stop[1], start[2]])
    bb = np.array([stop[0], stop[1], start[2]])
    tc = np.array([start[0], start[1], stop[2]])
    tr = np.array([stop[0], start[1], stop[2]])
    tl = np.array([start[0], stop[1], stop[2]])
    tb = np.array([stop[0], stop[1], stop[2]])
    lines = [
        np.linspace(bc, br, 100),
        np.linspace(br, bb, 100),
        np.linspace(bb, bl, 100),
        np.linspace(bl, bc, 100),
        np.linspace(bb, tb, 100),
        np.linspace(bl, tl, 100),
        np.linspace(bc, tc, 100),
        np.linspace(br, tr, 100),
        np.linspace(tc, tr, 100),
        np.linspace(tr, tb, 100),
        np.linspace(tb, tl, 100),
        np.linspace(tl, tc, 100),
    ]
    return lines


def compute_roi(images: Tuple[Image, Image, Image]):
    """Find the region of interest (roi) of our medical scan tensors.

    Args:
        images (List[sitk.SimpleITK.Image]):
            A tuple with the axial t2w (t2w), saggital t2w (sag),
            and coronal t2w (cor) images.
            See i.e. https://en.wikipedia.org/wiki/Anatomical_plane
            for a defenition of these terms.

    Returns:
        List[List[np.ndarray], List[slice]]:
            'intersections', a list of rois for every input scan
            and 'box_indices' a List with the start and end indices of
            every scan in the original tensor.
            See https://docs.python.org/3/library/functions.html#slice
            for more information regarding python slices.
    """
    # assert len(images) == 3

    # get the displacement vectors from the origin for every scan.
    origins = [np.asarray(img.GetOrigin()) for img in images]
    # find height, width and depth of every image-tensor.
    sizes = [np.asarray(img.GetSpacing()) * np.asarray(img.GetSize()) for img in images]
    # create a list with the rotation matrices for every scan.
    rotation = [np.asarray(img.GetDirection()).reshape(3, 3) for img in images]

    rects = []
    for pos, size in enumerate(sizes):
        lines = box_lines(size)
        rotated = [(rotation[pos] @ line.T).T for line in lines]
        shifted = [origins[pos] + line for line in rotated]
        rects.append(shifted)

    # find the intersection.
    rects_stacked = np.stack(rects)  # Had to rename because of mypy
    bbs = [
        (np.amin(rect, axis=(0, 1)), np.amax(rect, axis=(0, 1)))
        for rect in rects_stacked
    ]

    # compute intersection
    lower_end = np.amax(np.stack([bb[0] for bb in bbs], axis=0), axis=0)
    upper_end = np.amin(np.stack([bb[1] for bb in bbs], axis=0), axis=0)
    roi_bb = np.stack((lower_end, upper_end))
    roi_bb_size = roi_bb[1] - roi_bb[0]

    roi_bb_lines = np.stack(box_lines(roi_bb_size, roi_bb[0]))
    rects_stacked = np.concatenate([rects_stacked, np.expand_dims(roi_bb_lines, 0)])

    spacings = [image.GetSpacing() for image in images]
    # compute roi coordinates in image space.
    img_coord_rois = [
        (
            (np.linalg.inv(rot) @ (roi_bb[0] - offset).T).T / spacing,
            (np.linalg.inv(rot) @ (roi_bb[1] - offset).T).T / spacing,
        )
        for rot, offset, spacing in zip(rotation, origins, spacings)
    ]

    # use the roi-box to extract the corresponding array elements.
    arrays = [sitk.GetArrayFromImage(image).transpose((1, 2, 0)) for image in images]
    box_indices = []
    for ib, array in zip(img_coord_rois, arrays):
        img_indices = []
        low, up = np.amin(ib, axis=0), np.amax(ib, axis=0)
        # sometimes the prostate is centered on all images.
        # add a security margin.
        low = low - 20
        up = up + 20
        for pos, dim in enumerate(array.shape):

            def in_array(in_int, dim):
                in_int = int(in_int)
                in_int = 0 if in_int < 0 else in_int
                in_int = dim if in_int > dim else in_int
                return in_int

            img_indices.append(slice(in_array(low[pos], dim), in_array(up[pos], dim)))
        box_indices.append(img_indices)

    intersections = [i[tuple(box_inds)] for box_inds, i in zip(box_indices, arrays)]

    if False:
        # plot rects
        names = ["tra", "cor", "sag", "roi"]
        color_keys = list(mcolors.TABLEAU_COLORS.keys())
        fig = plt.figure()
        ax = fig.add_subplot(projection="3d")
        for pos, rect in enumerate(rects_stacked):
            color = color_keys[pos % len(color_keys)]
            for linepos, line in enumerate(rect):
                if linepos == 0:
                    ax.plot(
                        line[0, 0],
                        line[0, 1],
                        line[0, 2],
                        "s",
                        color=color,
                        label=names[pos],
                    )
                ax.plot(line[:, 0], line[:, 1], line[:, 2], "-.", color=color)
        plt.legend()
        plt.show()

        for pos, rect in enumerate(rects_stacked):
            color = color_keys[pos % len(color_keys)]
            for linepos, line in enumerate(rect):
                if linepos == 0:
                    plt.plot(line[0, 0], line[0, 1], "s", color=color, label=names[pos])
                plt.plot(line[:, 0], line[:, 1], "-.", color=color)
        plt.legend(loc="upper right")
        plt.title("X,Y-View")
        plt.show()

        for pos, rect in enumerate(rects_stacked):
            color = color_keys[pos % len(color_keys)]
            for linepos, line in enumerate(rect):
                if linepos == 0:
                    plt.plot(line[0, 1], line[0, 2], "s", color=color, label=names[pos])
                plt.plot(line[:, 1], line[:, 2], "-.", color=color)
        plt.legend(loc="upper right")
        plt.title("Y-Z-View")
        plt.show()

        # img_coord_tra = img_coord_rois[0]
        # sitk getShape and GetArrayFromImage return transposed results.

        plt.imshow(intersections[0][:, :, 11])
        plt.show()

    return intersections, box_indices


# def tversky(y_true, y_pred, alpha=.3, beta=.7):
#     """See: https://arxiv.org/pdf/1706.05721.pdf"""
#     y_true_f = jnp.reshape(y_true, -1)
#     y_pred_f = jnp.reshape(y_pred, -1)
#     intersection = jnp.sum(y_true_f * y_pred_f)
#     G_P = alpha * jnp.sum((1 - y_true_f) * y_pred_f)  # G not P
#     P_G = beta * jnp.sum(y_true_f * (1 - y_pred_f))  # P not G
#     return (intersection + 1.) / (intersection + 1. + G_P + P_G)
#
# def Tversky_loss(y_true, y_pred):
#     return -tversky(y_true, y_pred)
#
#
# def dice_coeff(logits, labels):
#     pred_probs = jax.nn.softmax(logits)
#     intersection = jnp.sum(labels * logits)
#     return ((2. * intersection + 1.) / (jnp.sum(labels) + jnp.sum(pred_probs) + 1.))*(-1.)


def disp_result(
    data: jnp.ndarray, labels: jnp.ndarray, id="", scan="", slice: int = 16
):
    """Plot the original image, network output and annotation."""
    colors = [
        [0.2422, 0.1504, 0.6603],
        [0.2647, 0.403, 0.9935],
        [0.1085, 0.6669, 0.8734],
        [0.2809, 0.7964, 0.5266],
        [0.9769, 0.9839, 0.0805],
    ]
    plt.title(f"net_seg_{id}_{scan}")
    data = (data[:, :, slice] / jnp.max(data)) * 255
    data = jnp.stack([data, data, data], -1)
    labels = labels[0, :, :, slice]
    color_labels = [list(map(lambda idx: colors[idx], row)) for row in labels]
    color_labels_stack = np.stack(color_labels) * 255
    mix = ((data + color_labels_stack) / 2.0).astype(np.uint8)
    plt.imshow(mix)
    plt.show()
    # plt.savefig(f"./export/net_seg_{id}_{scan}.png")
    # plt.clf()
