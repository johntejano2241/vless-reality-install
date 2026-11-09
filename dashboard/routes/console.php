<?php
use Illuminate\Support\Facades\Schedule;
Schedule::command('admin:refresh')->everyMinute()->withoutOverlapping(5);
