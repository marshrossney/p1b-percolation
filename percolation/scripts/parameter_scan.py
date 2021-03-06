import numpy as np
import scipy.optimize as optim
import matplotlib.pyplot as plt
import matplotlib as mpl
from tqdm import tqdm, tqdm_notebook
from pathlib import Path
import sys

# NOTE: the following would be better but results in ExperimentalFeatureWarning
# from tqdm.autonotebook import tqdm


def logistic(x, loc, steepness):
    """(One minus) the logistic function."""
    return 1 / (1 + np.exp(steepness * (x - loc)))


def parameter_scan(
    model,
    start,
    stop,
    repeats=50,
    num=50,
    parameter="inert_prob",
    notebook_friendly=True,
    outpath=None,
):
    """Loops over a range of values for a given parameter of the model, evolving the
    model forwards until it has either percolated or transmission has stopped.
    This is repeated a number of times for each value of the parameter.

    Inputs
    ------
    model: PandemicModel
        The model object.
    start: float
        Value of the parameter at which to start the parameter scan.
    stop: float
        Value at which to stop the prameter scan.
    num: int (optional)
        Number of values, equally spaced between `start` and `stop`, to loop over.
    repeats: int (optional)
        The number of simulations to run for each value of the parameter.
    parameter: str (optional)
        The parameter to evolve. Must be an attribute of model.
    notebook_friendly: bool (optional)
        Use tqdm bar specifically tailored for Jupyter notebooks.
    outpath: str (optional)
        Path to directory in which to save plot.
    """
    values = np.linspace(start, stop, num)

    if notebook_friendly:
        pbar = tqdm_notebook(
            total=(num * repeats),
            desc="Simulations completed",
        )
    else:
        pbar = tqdm(
            total=(num * repeats),
            desc="Simulations completed",
        )

    # --------------------------------------------------------------------------------
    #                                                           | Run parameter scan |
    #                                                           ----------------------
    percolation_fraction = np.empty(len(values))
    for i, value in enumerate(values):

        # Update model with new value for parameter
        setattr(model, parameter, value)

        # Run 'repeats' simulations and record the fraction that percolate
        percolation_fraction[i], _ = model.estimate_percolation_prob(
            repeats, print_result=False
        )

        pbar.update(repeats)

    pbar.close()

    # --------------------------------------------------------------------------------
    #                                                               | Compute errors |
    #                                                               ------------------
    if parameter == "inert_prob" and model.network.n_links == 1:
        # In the case of one connection per node, the SE is known in terms of Bernoulli prob
        r = model.network.n_rows
        c = model.network.n_cols
        p = 1 - (1 - (1 - values) ** r) ** c
        errors = np.sqrt(p * (1 - p) / repeats)
    else:
        # Otherwise errors are SE on the sample mean for a Binomial distribution
        errors = np.sqrt((percolation_fraction * (1 - percolation_fraction)) / repeats)

    # Enforce a minimum error (should base on the Geometric distribution - num steps
    # before first 'hit')
    errors = np.fmax(errors, 1 / repeats)  # TODO this needs justifying

    # Modify error bars for plot so that they don't fall outside [0, 1]
    errors_above = errors.copy()
    errors_below = errors.copy()
    upper_cap = percolation_fraction + errors
    lower_cap = percolation_fraction - errors
    cap_above_one = upper_cap > 1
    cap_below_zero = lower_cap < 0
    errors_above[cap_above_one] -= upper_cap[cap_above_one] - 1
    errors_below[cap_below_zero] += lower_cap[cap_below_zero]
    errors_for_plot = np.stack((errors_below, errors_above), axis=0)

    # --------------------------------------------------------------------------------
    #                                                                    | Plot data |
    #                                                                    -------------

    spec = mpl.gridspec.GridSpec(nrows=2, ncols=1, height_ratios=(3, 1))
    fig = plt.figure()

    ax = fig.add_subplot(spec[0])
    ax2 = fig.add_subplot(spec[1])

    ax.set_title("Parameter scan")
    ax.set_ylabel("Percolation fraction ($f$)")
    ax2.set_ylabel("Residuals")
    ax2.set_xlabel(parameter.replace("_", " "))
    if parameter == "inert_prob":
        ax2.set_xlabel("Inert probability ($q$)")  # this is all students will use
    ax.xaxis.set_ticklabels([])

    ax.errorbar(
        x=values,
        y=percolation_fraction,
        yerr=errors_for_plot,
        fmt="o",
        color="green",
        capsize=2,
        elinewidth=1.5,
        ecolor="black",
        capthick=1.5,
        markeredgecolor="black",
        label="data",
        zorder=0,
    )

    fit_x = np.linspace(values.min(), values.max(), 1000)

    # In this case we just plot the theoretical curve
    if parameter == "inert_prob" and model.network.n_links == 1:
        r = model.network.n_rows
        c = model.network.n_cols
        fit_values = 1 - (1 - (1 - fit_x) ** r) ** c
        residuals = percolation_fraction - (1 - (1 - (1 - values) ** r) ** c)
        label = "theoretical probability"

    # Otherwise we attempt to fit a logistic curve with two parameters
    else:
        popt, pcov = optim.curve_fit(
            logistic,
            xdata=values,
            ydata=percolation_fraction,
            sigma=errors,
            p0=(0.5, 10),
            bounds=((0, 0), (1, np.inf)),
        )

        loc, steepness = popt
        e_loc, e_steepness = np.sqrt(pcov.diagonal())
        print(f"Mid-point of transition is q_0 = {loc} +/- {e_loc}")
        print(f"Steepness parameter is lambda = {steepness} +/- {e_steepness}")

        fit_values = logistic(fit_x, loc=loc, steepness=steepness)
        residuals = percolation_fraction - logistic(
            values, loc=loc, steepness=steepness
        )
        label = r"least squares fit"

    ax.plot(
        fit_x,
        fit_values,
        color="r",
        linestyle="--",
        linewidth="2.0",
        label=label,
        zorder=1,
    )

    # Plot residuals
    ax2.errorbar(
        x=values,
        y=residuals,
        yerr=errors_for_plot,
        fmt="o",
        color="green",
        capsize=2,
        elinewidth=1.5,
        ecolor="black",
        capthick=1.5,
        markeredgecolor="black",
        label="data",
        zorder=0,
    )
    ax2.axhline(
        0,
        color="r",
        linestyle="--",
        linewidth="2.0",
        label=label,
        zorder=1,
    )

    ax.legend()

    if outpath is not None:
        outpath = Path(outpath)
        outpath.mkdir(parents=True, exist_ok=True)
        fig.savefig(outpath / f"parameter_scan_L{model.network.n_rows}.png")
    else:
        plt.show()
