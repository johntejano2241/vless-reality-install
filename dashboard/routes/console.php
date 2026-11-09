<?php
use Illuminate\Support\Facades\Schedule;
Schedule::command('admin:refresh')->everyMinute()->withoutOverlapping(5);
Schedule::command('admin:dispatch-pending')->everyMinute()->withoutOverlapping(5);
