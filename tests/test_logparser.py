from easyfoam.foam.logparser import LogParser

STEADY = """\
Starting time loop

Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.0538101, No Iterations 1
smoothSolver:  Solving for Uy, Initial residual = 0.5, Final residual = 0.03, No Iterations 1
GAMG:  Solving for p, Initial residual = 1, Final residual = 0.068427, No Iterations 17
time step continuity errors : sum local = 1.19733, global = 0.179883, cumulative = 0.179883
smoothSolver:  Solving for omega, Initial residual = 0.02, Final residual = 0.001, No Iterations 2
ExecutionTime = 0.26 s  ClockTime = 0 s

Time = 2

smoothSolver:  Solving for Ux, Initial residual = 0.25, Final residual = 0.01, No Iterations 1
smoothSolver:  Solving for Uy, Initial residual = 0.125, Final residual = 0.01, No Iterations 1
GAMG:  Solving for p, Initial residual = 0.3, Final residual = 0.02, No Iterations 9
ExecutionTime = 0.51 s  ClockTime = 1 s

End
"""

TRANSIENT = """\
Courant Number mean: 0.222158 max: 0.852134
Time = 0.005s

PIMPLE: Iteration 1
DILUPBiCGStab:  Solving for Ux, Initial residual = 1.5e-05, Final residual = 1e-09, No Iterations 1
GAMG:  Solving for p, Initial residual = 0.4, Final residual = 0.01, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.05, Final residual = 1e-07, No Iterations 20
ExecutionTime = 1.5 s  ClockTime = 2 s
"""

FATAL = """\
Time = 1

--> FOAM FATAL ERROR: (openfoam-2506)
Maximum number of iterations exceeded: 100

    From function Foam::scalar thermo::T()
    in file thermo.C at line 73.

FOAM aborting
"""


def feed_all(text):
    parser = LogParser()
    for line in text.splitlines():
        parser.feed(line)
    return parser


def test_steady_log_gives_one_residual_per_field_per_iteration():
    p = feed_all(STEADY)
    assert p.times == [1.0, 2.0]
    assert p.residuals["Ux"] == [(1.0, 1.0), (2.0, 0.25)]
    assert p.residuals["p"] == [(1.0, 1.0), (2.0, 0.3)]


def test_field_missing_in_a_later_step_keeps_its_earlier_points_only():
    p = feed_all(STEADY)
    assert p.residuals["omega"] == [(1.0, 0.02)]


def test_only_the_first_solve_of_a_field_in_a_time_step_is_recorded():
    p = feed_all(TRANSIENT)
    assert p.residuals["p"] == [(0.005, 0.4)]


def test_time_with_unit_suffix_and_courant_number_are_parsed():
    p = feed_all(TRANSIENT)
    assert p.times == [0.005]
    assert p.courant == [(0.222158, 0.852134)]


def test_execution_time_and_end_marker():
    p = feed_all(STEADY)
    assert p.execution_time == 0.51
    assert p.finished is True
    assert p.error is None


def test_continuity_errors_are_recorded_per_time_step():
    p = feed_all(STEADY)
    assert p.continuity == [(1.0, 1.19733, 0.179883)]


def test_fatal_error_message_is_captured_and_run_is_not_finished():
    p = feed_all(FATAL)
    assert p.finished is False
    assert p.error.startswith("FOAM FATAL ERROR")
    assert "Maximum number of iterations exceeded: 100" in p.error


def test_lines_before_the_first_time_step_are_ignored():
    p = LogParser()
    p.feed("GAMG:  Solving for p, Initial residual = 1, Final residual = 0.1, No Iterations 4")
    assert p.residuals == {}
    assert p.times == []
